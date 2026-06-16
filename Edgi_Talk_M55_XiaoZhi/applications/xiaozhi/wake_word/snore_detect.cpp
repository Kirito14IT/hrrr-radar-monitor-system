/*
 * Capture microphone audio and run the local snore detector.
 */

#include <rtthread.h>
#include <rtdevice.h>
#include <board.h>
#include <string.h>

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "snore.det"
#define DBG_LVL DBG_LOG
#include <rtdbg.h>

#include "edge-impulse-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "edge-impulse-sdk/tensorflow/lite/schema/schema_generated.h"

#include "tflite-model/tflite-resolver.h"

// Avoid RT-Thread legacy ALIGN macro clash
#ifdef ALIGN
#undef ALIGN
#endif
#include "tflite-model/snore_model_data.h"

// UI helpers
#include "xiaozhi_ui.h"
#include "backend_target_config.h"
#include "audio_capture_hub.h"

extern "C" void xz_trigger_care_alarm(void);

/* CMSIS-DSP for FFT/Mel */
#include "edge-impulse-sdk/CMSIS/DSP/Include/arm_math.h"
#include <cmath>  // logf, fabsf

/* --- NEW: For HTTP Socket --- */
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h> // for close
/* --- END NEW --- */

/* Hann window constant */
#define SNORE_PI 3.14159265358979323846f

/* Audio device name */
#ifndef BSP_XIAOZHI_MIC_DEVICE_NAME
#define BSP_XIAOZHI_MIC_DEVICE_NAME "mic0"
#endif

/* --- NEW: Configuration for DB sending --- */
#ifndef DB_SEND_TARGET_IP
#define DB_SEND_TARGET_IP "192.168.0.101"  // Replace with your target IP
#endif

#ifndef DB_SEND_TARGET_PORT
#define DB_SEND_TARGET_PORT 8081           // Replace with your target port
#endif

#define DB_HISTORY_SIZE 10                 // Store 10 seconds of dB readings
#define DB_THREAD_STACK_SIZE 2048
#define DB_THREAD_PRIORITY 17  // Higher than main snore thread (18)
#define DB_THREAD_TICK 10

/* NEW: Heartbeat configuration */
#define HB_INTERVAL_MS 1000                // Send a snore score heartbeat every 1s
#define HB_THREAD_STACK_SIZE 2048
#define HB_THREAD_PRIORITY 18              // Same as snore detection (independent work)
#define HB_THREAD_TICK 10
/* END NEW */
/* --- END NEW --- */

namespace {

// Board LEDs (from cycfg_pins.h: P16_7 red, P16_6 green, P16_5 blue)
constexpr int kLedRed = GET_PIN(16, 7);
constexpr int kLedGreen = GET_PIN(16, 6);
constexpr int kLedBlue = GET_PIN(16, 5);
// LED polarity:
// - active-high: PIN_HIGH=ON, PIN_LOW=OFF
// - active-low : PIN_LOW =ON, PIN_HIGH=OFF
// If your LEDs behave inverted, toggle this value.
constexpr int kLedActiveLow = 0;

static void led_write(int pin, rt_bool_t on)
{
    rt_pin_write(pin, (on ^ (kLedActiveLow ? 1 : 0)) ? PIN_HIGH : PIN_LOW);
}

static void leds_init_once(void)
{
    static rt_bool_t inited = RT_FALSE;
    if (inited)
        return;
    inited = RT_TRUE;

    rt_pin_mode(kLedRed, PIN_MODE_OUTPUT);
    rt_pin_mode(kLedGreen, PIN_MODE_OUTPUT);
    rt_pin_mode(kLedBlue, PIN_MODE_OUTPUT);

    // Default: detector not running -> red on, green off, blue off
    led_write(kLedRed, RT_TRUE);
    led_write(kLedGreen, RT_FALSE);
    led_write(kLedBlue, RT_FALSE);
}

constexpr int kSampleRate = 16000; // used for info only
constexpr size_t kInputSamples = 32000; // raw PCM samples (2 seconds @ 16kHz)

// Snore model: input [1,60,20] = 1200 bytes (log-Mel spectrogram features)

// DSP params for feature extraction
constexpr int kFFTSize = 512;
constexpr int kFFTOutputSize = 257;  // FFT size / 2 + 1
constexpr int kHopSize = 160;        // model.py SlidingWindowTime stride: 10ms @ 16kHz
constexpr int kNumFrames = 60;       // frames to accumulate (match model)
constexpr int kMelBins = 20;         // output mel bins
constexpr int kFeatureSize = 60 * 20; // 1200
constexpr int kFeatureWindowSamples = kFFTSize + (kNumFrames - 1) * kHopSize; // 9952
constexpr float kMelClipMin = 0.000316227766016f;
static const int kMelFilterPoints[kMelBins + 2] = {
    9, 13, 16, 21, 25, 31, 37, 43, 50, 58, 67,
    77, 87, 99, 113, 127, 144, 162, 182, 204, 229, 256
};

// Detection threshold (0.0 ~ 1.0)
constexpr float kSnoreThreshold = 0.6f;
// Cooldown only prevents repeated triggers; lower = more responsive.
constexpr uint32_t kDetectCooldownMs = 500;
// Sliding window hop size (in samples). 16000 @16kHz ~= 1000ms.
constexpr size_t kHopSamples = 16000;

constexpr size_t kTensorArenaSize = 256 * 1024;
__attribute__((aligned(16))) static uint8_t tensor_arena[kTensorArenaSize] rt_section(".m33_m55_shared_hyperram");

static tflite::MicroInterpreter *g_interp = RT_NULL;
static TfLiteTensor *g_in = RT_NULL;
static TfLiteTensor *g_out = RT_NULL;
static rt_tick_t g_last_detect_tick = 0;
static rt_thread_t g_snore_tid = RT_NULL;
static volatile rt_bool_t g_snore_running = RT_FALSE;
static rt_thread_t g_db_tid = RT_NULL; // NEW: Thread handle for dB detection
static volatile rt_bool_t g_db_running = RT_FALSE; // NEW: Flag for dB thread
static rt_thread_t g_hb_tid = RT_NULL; // NEW: Heartbeat thread handle
static volatile rt_bool_t g_hb_running = RT_FALSE; // NEW: Heartbeat running flag
static float g_db_history[DB_HISTORY_SIZE] rt_section(".m33_m55_shared_hyperram"); // NEW: Ring buffer for dB history
static int g_db_history_index = 0; // NEW: Index for the ring buffer
static rt_mutex_t g_db_mutex = RT_NULL; // NEW: Mutex to protect access to history and index
static rt_mutex_t g_score_mutex = RT_NULL; // NEW: Mutex for the latest snore score
static rt_mutex_t g_lifecycle_mutex = RT_NULL;
static volatile float g_latest_score = 0.0f; // NEW: Latest snore score (shared with heartbeat thread)
static volatile rt_bool_t g_latest_detected = RT_FALSE; // NEW: Latest snore detection flag
static volatile float g_latest_dbfs = 0.0f; // NEW: Latest board-computed audio level for heartbeat
static volatile rt_bool_t g_latest_dbfs_valid = RT_FALSE; // NEW: Whether g_latest_dbfs is ready

static int lifecycle_lock(void)
{
    if (!g_lifecycle_mutex)
    {
        g_lifecycle_mutex = rt_mutex_create("snorelife", RT_IPC_FLAG_FIFO);
        if (!g_lifecycle_mutex)
        {
            LOG_E("snore: create lifecycle mutex failed");
            return -RT_ENOMEM;
        }
    }

    return rt_mutex_take(g_lifecycle_mutex, RT_WAITING_FOREVER);
}

static void lifecycle_unlock(void)
{
    if (g_lifecycle_mutex)
    {
        rt_mutex_release(g_lifecycle_mutex);
    }
}

static void wait_for_capture_threads(unsigned int timeout_ms)
{
    unsigned int waited_ms = 0;
    while ((g_snore_tid || g_db_tid) && waited_ms < timeout_ms)
    {
        rt_thread_mdelay(20);
        waited_ms += 20;
    }

    if (g_snore_tid || g_db_tid)
    {
        LOG_W("snore: capture stop timed out, detector=%p uploader=%p",
              g_snore_tid, g_db_tid);
    }
}

static void wait_for_heartbeat_thread(unsigned int timeout_ms)
{
    unsigned int waited_ms = 0;
    while (g_hb_tid && waited_ms < timeout_ms)
    {
        rt_thread_mdelay(20);
        waited_ms += 20;
    }

    if (g_hb_tid)
    {
        LOG_W("snore: heartbeat stop timed out, thread=%p", g_hb_tid);
    }
}

/* NEW: Global variables for blue LED blink (moved inside namespace) */
static rt_tick_t g_blue_blink_until = 0;
static rt_tick_t g_blue_blink_next_toggle = 0;
static rt_bool_t g_blue_blink_on = RT_FALSE;
/* END NEW */

/* ── FFT / Mel workspace (static to save stack) ─────────────────────── */
static arm_rfft_fast_instance_f32 g_fft_inst;
ALIGN(16) static float g_fft_buf[kFFTSize] rt_section(".m33_m55_shared_hyperram");
ALIGN(16) static float g_fft_out[kFFTSize] rt_section(".m33_m55_shared_hyperram");
ALIGN(16) static float g_magnitude[kFFTOutputSize] rt_section(".m33_m55_shared_hyperram");
ALIGN(16) static float g_frame_f32[kFFTSize] rt_section(".m33_m55_shared_hyperram");
ALIGN(16) static float g_mel_spectrogram[kNumFrames][kMelBins] rt_section(".m33_m55_shared_hyperram");

/* Mel filterbank weights: 20 filters × 257 bins (computed at init) */
static float g_mel_weights[kMelBins][kFFTOutputSize] rt_section(".m33_m55_shared_hyperram");

/* Quantization params (cached from tensor) */
static float g_input_scale = 0.0f;
static int g_input_zero_point = 0;
static float g_output_scale = 0.0f;
static int g_output_zero_point = 0;

/* NEW: Function to calculate RMS and dB */
static float calculate_db(const int16_t* samples, size_t num_samples) {
    if (num_samples == 0) return 0.0f;

    double sum_sq = 0.0;
    for (size_t i = 0; i < num_samples; i++) {
        double s = (double)samples[i];
        sum_sq += s * s;
    }
    double mean_sq = sum_sq / (double)num_samples;
    double rms = sqrt(mean_sq);

    // Calculate dB relative to full scale (32768)
    // Add small epsilon to avoid log(0)
    float db = 20.0f * log10f((float)rms / 32768.0f + 1e-9f);
    return db;
}
/* END NEW */


/* NEW: Function for blue LED blink (moved inside namespace and made static) */
static void blue_blink_for_ms(uint32_t duration_ms, uint32_t period_ms)
{
    /* Non-blocking blink: handled in the detect thread loop */
    if (period_ms == 0)
        period_ms = 100;
    const rt_tick_t now = rt_tick_get();
    g_blue_blink_until = now + rt_tick_from_millisecond(duration_ms);
    g_blue_blink_next_toggle = now;
    g_blue_blink_on = RT_FALSE;
}
/* END NEW */


static void print_tensor_dims(TfLiteTensor *t, const char *name)
{
    if (!t || !t->dims) {
        LOG_I("%s: tensor is null or no dims", name);
        return;
    }
    int dims = t->dims->size;
    LOG_I("%s: type=%d, dims=%d, shape=[", name, (int)t->type, dims);
    for (int i = 0; i < dims; i++) {
        rt_kprintf("%d", t->dims->data[i]);
        if (i < dims - 1) rt_kprintf(",");
    }
    rt_kprintf("], bytes=%d\n", (int)t->bytes);
}

/* ================================================================
 *  Pre-compute triangular Mel filterbank weights
 * ================================================================ */
static void compute_mel_weights(void)
{
    memset(g_mel_weights, 0, sizeof(g_mel_weights));
    for (int m = 0; m < kMelBins; m++) {
        const int n0 = kMelFilterPoints[m];
        const int n1 = kMelFilterPoints[m + 1];
        const int n2 = kMelFilterPoints[m + 2];

        for (int k = n0; k < n1 && k < kFFTOutputSize; k++) {
            if (k >= 0 && n1 > n0) {
                g_mel_weights[m][k] = (float)(k - n0) / (float)(n1 - n0);
            }
        }
        for (int k = n1; k < n2 && k < kFFTOutputSize; k++) {
            if (k >= 0 && n2 > n1) {
                g_mel_weights[m][k] = 1.0f - ((float)(k - n1) / (float)(n2 - n1));
            }
        }
    }

    LOG_I("Mel weights computed from fixed model.py points for %d filters x %d bins",
          kMelBins, kFFTOutputSize);
}

static int init_model()
{
    if (g_interp)
        return 0;

    const tflite::Model *model = tflite::GetModel(snore_model_tflite);
    if (!model)
    {
        LOG_E("init_model: GetModel failed");
        return -RT_ERROR;
    }
    LOG_I("init_model: model=%p, arena=%d, subgraphs=%d",
          model, (int)kTensorArenaSize,
          (int)model->subgraphs()->size());

    EI_TFLITE_RESOLVER
    static tflite::MicroInterpreter interp(model, resolver, tensor_arena, kTensorArenaSize);

    TfLiteStatus st = interp.AllocateTensors(true);
    if (st != kTfLiteOk)
    {
        LOG_E("init_model: AllocateTensors failed status=%d, arena=%d", st, (int)kTensorArenaSize);
        LOG_I("init_model: subgraphs=%d, inputs=%d, outputs=%d",
              (int)model->subgraphs()->size(),
              (int)interp.inputs_size(), (int)interp.outputs_size());
        return -RT_ERROR;
    }

    g_interp = &interp;
    g_in = g_interp->input(0);
    g_out = g_interp->output(0);

    /* Print tensor dimensions for debugging */
    // print_tensor_dims(g_in, "INPUT");
    // print_tensor_dims(g_out, "OUTPUT");

    /* Cache quantization params from tensor */
    g_input_scale = g_in->params.scale;
    g_input_zero_point = g_in->params.zero_point;
    g_output_scale = g_out->params.scale;
    g_output_zero_point = g_out->params.zero_point;
    LOG_I("init_model: input quant scale=%.6f zp=%d, output quant scale=%.6f zp=%d",
          g_input_scale, g_input_zero_point, g_output_scale, g_output_zero_point);

    /* Initialize CMSIS-DSP FFT */
    if (arm_rfft_fast_init_f32(&g_fft_inst, kFFTSize) != ARM_MATH_SUCCESS) {
        LOG_E("init_model: arm_rfft_fast_init_f32 failed");
        return -RT_ERROR;
    }

    /* Pre-compute Mel filterbank weights */
    compute_mel_weights();

    LOG_I("init_model: OK");
    return 0;
}

#ifdef RT_USING_FINSH
static void led_probe(void)
{
    leds_init_once();
    rt_kprintf("\n[led_probe] Toggle LED pins HIGH/LOW: R=P16_7, G=P16_6, B=P16_5\n");
    rt_kprintf("[led_probe] Please observe which level turns each LED ON.\n\n");

    struct
    {
        const char *name;
        int pin;
    } leds[] = {
        {"RED  (P16_7)", kLedRed},
        {"GREEN(P16_6)", kLedGreen},
        {"BLUE (P16_5)", kLedBlue},
    };

    for (size_t i = 0; i < sizeof(leds) / sizeof(leds[0]); i++)
    {
        rt_kprintf("[led_probe] %s: write HIGH for 1000ms\n", leds[i].name);
        rt_pin_write(leds[i].pin, PIN_HIGH);
        rt_thread_mdelay(1000);

        rt_kprintf("[led_probe] %s: write LOW  for 1000ms\n", leds[i].name);
        rt_pin_write(leds[i].pin, PIN_LOW);
        rt_thread_mdelay(1000);

        rt_kprintf("[led_probe] %s: OFF via led_write(false)\n\n", leds[i].name);
        led_write(leds[i].pin, RT_FALSE);
        rt_thread_mdelay(300);
    }

    rt_kprintf("[led_probe] Done.\n");
}
MSH_CMD_EXPORT(led_probe, Toggle LED pins HIGH/LOW to determine polarity);
#endif

static inline int8_t clamp_i8(int32_t v)
{
    if (v > 127)
        return 127;
    if (v < -128)
        return -128;
    return (int8_t)v;
}

/* ================================================================
 *  Compute one Mel spectrogram frame (20 bins) from 512 samples
 * ================================================================ */
static void compute_mel_spectrum(const float *samples_512, float *mel_out)
{
    /* Apply Hann window */
    for (int i = 0; i < kFFTSize; i++) {
        float w = 0.5f * (1.0f - cosf(2.0f * SNORE_PI * i / (kFFTSize - 1)));
        g_fft_buf[i] = samples_512[i] * w;
    }

    /* Forward FFT */
    arm_rfft_fast_f32(&g_fft_inst, g_fft_buf, g_fft_out, 0);

    /* Compute magnitude spectrum (257 bins) */
    g_magnitude[0] = fabsf(g_fft_out[0]);  // DC
    arm_cmplx_mag_f32(&g_fft_out[2], &g_magnitude[1], kFFTSize / 2 - 1);
    g_magnitude[kFFTOutputSize - 1] = fabsf(g_fft_out[1]);  // Nyquist

    /* Apply Mel filterbank */
    for (int m = 0; m < kMelBins; m++) {
        float sum = 0.0f;
        for (int k = 0; k < kFFTOutputSize; k++) {
            sum += g_magnitude[k] * g_mel_weights[m][k];
        }
        if (sum < kMelClipMin) {
            sum = kMelClipMin;
        }
        mel_out[m] = logf(sum);
    }
}

/* ================================================================
 *  Quantize float to int8 using cached scale/zero_point
 * ================================================================ */
static inline int8_t quantize_f32(float value)
{
    int32_t q = (int32_t)std::roundf(value / g_input_scale) + g_input_zero_point;
    return clamp_i8(q);
}

/*
 * PDM driver configuration (same as wakeword).
 */
#ifdef ENABLE_STEREO_INPUT_FEED
    #define PDM_FRAME_SAMPLES 320
    #define PDM_MONO_FRAME_SAMPLES (PDM_FRAME_SAMPLES / 2)
    #define PDM_IS_STEREO 1
#else
    #define PDM_FRAME_SAMPLES 160
    #define PDM_MONO_FRAME_SAMPLES PDM_FRAME_SAMPLES
    #define PDM_IS_STEREO 0
#endif
#define PDM_FRAME_SIZE (PDM_FRAME_SAMPLES * sizeof(int16_t))

} // namespace

static int snore_infer_from_pcm(const int16_t *pcm, float *out_score, rt_bool_t *out_detected)
{
#ifndef RT_USING_AUDIO
    LOG_E("RT_USING_AUDIO not enabled");
    return -RT_ERROR;
#else
    if (init_model() != 0)
        return -RT_ERROR;

    leds_init_once();

    // Check model input requirements
    if (!g_in || !g_out) {
        LOG_E("Tensor not initialized");
        return -RT_ERROR;
    }

    // Snore model: INPUT [1,60,20] = 1200 bytes int8
    // Expected: Mel spectrogram features (60 frames x 20 bins)
    const int kExpectedInputBytes = 1200;
    const int kFeatureFrames = 60;
    const int kFeatureBins = 20;

    if (g_in->type != kTfLiteInt8) {
        LOG_E("Unexpected input type: %d", g_in->type);
        return -RT_ERROR;
    }

    if (g_in->bytes != kExpectedInputBytes) {
        LOG_E("Input bytes mismatch: expected=%d, got=%d",
              kExpectedInputBytes, (int)g_in->bytes);
        return -RT_ERROR;
    }

    if (g_out->type != kTfLiteInt8 || g_out->bytes < 2) {
        LOG_E("Unexpected output tensor: type=%d, bytes=%d", g_out->type, (int)g_out->bytes);
        return -RT_ERROR;
    }

    /*
     * Extract Mel spectrogram from PCM.
     * Process the latest model.py-compatible window from the 2s snapshot:
     * 60 frames, 512-sample FFT window, 160-sample stride => 9952 samples.
     */
    const int feature_start = (int)kInputSamples - kFeatureWindowSamples;

    for (int f = 0; f < kFeatureFrames; f++) {
        int offset = feature_start + (f * kHopSize);
        if (offset + kFFTSize > kInputSamples) break;

        /* Convert int16 PCM → float [-1.0, 1.0) */
        for (int i = 0; i < kFFTSize; i++) {
            g_frame_f32[i] = (float)pcm[offset + i] / 32768.0f;
        }

        /* Compute Mel spectrogram frame (20 bins) */
        compute_mel_spectrum(g_frame_f32, g_mel_spectrogram[f]);

        /* Quantize and write to tensor input
         * Tensor layout: [batch=1][frame][mel_bin][channel=1]
         * Flattened: [frame * 20 + bin] */
        int t_off = f * kFeatureBins;
        for (int b = 0; b < kFeatureBins; b++) {
            g_in->data.int8[t_off + b] = quantize_f32(g_mel_spectrogram[f][b]);
        }
    }

    if (g_interp->Invoke() != kTfLiteOk)
    {
        LOG_E("Invoke failed");
        return -RT_ERROR;
    }

    /* Debug: print input data values (first 10) */
    // LOG_I("infer: input[0..9]=%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
    //       g_in->data.int8[0], g_in->data.int8[1], g_in->data.int8[2],
    //       g_in->data.int8[3], g_in->data.int8[4], g_in->data.int8[5],
    //       g_in->data.int8[6], g_in->data.int8[7], g_in->data.int8[8], g_in->data.int8[9]);
    /* Debug: print first frame Mel values (first 3 bins) */
    // LOG_I("infer: mel[0..2]=%.2f,%.2f,%.2f",
    //       g_mel_spectrogram[0][0], g_mel_spectrogram[0][1], g_mel_spectrogram[0][2]);

    // Model output: [1,2] - class 0: unlabelled, class 1: snore
    // Use class 1 (snore) probability
    const int8_t out1 = g_out->data.int8[1];
    float snore_score = ((int)out1 - g_output_zero_point) * g_output_scale;
    if (snore_score < 0.0f) snore_score = 0.0f;
    if (snore_score > 1.0f) snore_score = 1.0f;

    // LOG_I("infer: output[0]=%d, output[1]=%d, snore=%.3f",
    //       (int)g_out->data.int8[0], (int)out1, snore_score);

    const rt_tick_t now = rt_tick_get();
    const rt_bool_t cooldown_ok = (g_last_detect_tick == 0) ||
                                  ((now - g_last_detect_tick) >= rt_tick_from_millisecond(kDetectCooldownMs));

    const rt_bool_t detected = (snore_score >= kSnoreThreshold && cooldown_ok);

    if (detected)
    {
        g_last_detect_tick = now;
        LOG_W("SNORE DETECTED: score=%.3f (raw=%d) threshold=%.2f", snore_score, (int)out1, kSnoreThreshold);
    }
    else
    {
        LOG_I("NO SNORE: score=%.3f (raw=%d) threshold=%.2f%s",
              snore_score, (int)out1, kSnoreThreshold,
              (snore_score >= kSnoreThreshold && !cooldown_ok) ? " (cooldown)" : "");
    }

    if (out_score)
        *out_score = snore_score;
    if (out_detected)
        *out_detected = detected;

    return RT_EOK;
#endif
}

#if 0
/* Retained only as historical reference. Continuous raw-audio upload is not
 * part of the shared-microphone runtime because it requires a 320 KB chunk. */
static int socket_send_all(int sockfd, const void *data, size_t length)
{
    const uint8_t *cursor = (const uint8_t *)data;
    size_t total_sent = 0;

    while (total_sent < length)
    {
        const size_t remaining = length - total_sent;
        const size_t send_size = remaining > 4096 ? 4096 : remaining;
        const ssize_t sent = send(sockfd, cursor + total_sent, send_size, 0);
        if (sent <= 0)
        {
            LOG_E("audio_send: send failed, errno=%d", errno);
            return -1;
        }
        total_sent += (size_t)sent;
    }

    return 0;
}

/* NEW: Thread to send raw audio via HTTP continuously
 *  - Collects 10s chunks from the mic
 *  - POSTs each chunk to the backend as soon as it is ready
 *  - Loops until g_db_running is cleared (by snore_detect_stop / audio_send_stop)
 */
static void audio_send_thread_entry(void *parameter)
{
    (void)parameter;
    rt_device_t local_mic_dev = RT_NULL;

    // 10 seconds of mono audio at 16kHz = 160000 samples
    constexpr size_t kChunkSamples   = (size_t)kSampleRate * 10;
    constexpr int    kMaxErrStreak   = 5;
    constexpr uint32_t kErrBackoffMs = 1000;

    LOG_I("audio_send: thread started (continuous HTTP mode), chunk=%d samples (%.1fs)",
          (int)kChunkSamples, (float)kChunkSamples / (float)kSampleRate);

    local_mic_dev = rt_device_find(BSP_XIAOZHI_MIC_DEVICE_NAME);
    if (!local_mic_dev)
    {
        LOG_E("audio_send: cannot find audio device '%s'", BSP_XIAOZHI_MIC_DEVICE_NAME);
        g_db_running = RT_FALSE;
        g_db_tid = RT_NULL;
        return;
    }

    if (rt_device_open(local_mic_dev, RT_DEVICE_FLAG_RDONLY) != RT_EOK)
    {
        LOG_E("audio_send: cannot open audio device");
        g_db_running = RT_FALSE;
        g_db_tid = RT_NULL;
        return;
    }
    LOG_I("audio_send: opened mic device");

    // One reusable buffer for the chunk (recycled across iterations to avoid fragmentation)
    static int16_t audio_buffer[kChunkSamples] rt_section(".m33_m55_shared_hyperram");

    int chunk_index = 0;
    int err_streak  = 0;

    while (g_db_running)
    {
        // ── Phase 1: collect 10 seconds of audio ─────────────────────
        size_t collected = 0;
        const rt_tick_t collect_start   = rt_tick_get();
        const rt_tick_t collect_deadline = collect_start + rt_tick_from_millisecond(11000); // safety: 11s

        while (g_db_running && collected < kChunkSamples)
        {
            if (rt_tick_get() > collect_deadline)
            {
                LOG_W("audio_send: collect deadline reached, got %d/%d samples",
                      (int)collected, (int)kChunkSamples);
                break;
            }

            int16_t pdm_frame[PDM_FRAME_SAMPLES];
            const rt_size_t read_size = rt_device_read(local_mic_dev, 0, pdm_frame, PDM_FRAME_SIZE);
            if (read_size == 0)
            {
                if (!g_db_running) break;
                rt_thread_mdelay(1);
                continue;
            }
            if (!g_db_running) break;

            const size_t total_sample = read_size / sizeof(int16_t);
#if PDM_IS_STEREO
            // Interleaved L,R,L,R treated as consecutive mono samples
            for (size_t i = 0; i < total_sample && collected < kChunkSamples; i++)
            {
                audio_buffer[collected++] = pdm_frame[i];
            }
#else
            for (size_t i = 0; i < total_sample && collected < kChunkSamples; i++)
            {
                audio_buffer[collected++] = pdm_frame[i];
            }
#endif
        }

        if (!g_db_running)
        {
            LOG_I("audio_send: stop requested during collect, exiting");
            break;
        }

        const uint32_t collect_ms =
            (uint32_t)((rt_tick_get() - collect_start) * 1000 / RT_TICK_PER_SECOND);
        LOG_I("audio_send: chunk %d collected %d samples in %u ms, sending...",
              chunk_index, (int)collected, collect_ms);

        // ── Phase 2: send chunk via HTTP ─────────────────────────────
        char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
        int backend_port = DB_SEND_TARGET_PORT;
        backend_target_get(DB_SEND_TARGET_IP, DB_SEND_TARGET_PORT,
                           backend_host, sizeof(backend_host), &backend_port);

        char http_header[256];
        const size_t audio_bytes = collected * sizeof(audio_buffer[0]);
        int header_len = snprintf(http_header, sizeof(http_header),
            "POST /audio HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Content-Type: audio/wav\r\n"
            "Content-Length: %u\r\n"
            "Connection: close\r\n"
            "\r\n",
            backend_host, backend_port, (unsigned)audio_bytes);
        if (header_len <= 0 || header_len >= (int)sizeof(http_header))
        {
            LOG_E("audio_send: HTTP header overflow");
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        int sockfd = socket(AF_INET, SOCK_STREAM, 0);
        if (sockfd < 0)
        {
            LOG_E("audio_send: socket() failed, errno=%d", errno);
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        struct sockaddr_in serv_addr;
        memset(&serv_addr, 0, sizeof(serv_addr));
        serv_addr.sin_family      = AF_INET;
        serv_addr.sin_port        = htons(backend_port);
        serv_addr.sin_addr.s_addr = inet_addr(backend_host);

        if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) != 0)
        {
            LOG_E("audio_send: connect %s:%d failed, errno=%d",
                  backend_host, backend_port, errno);
            close(sockfd);
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        const rt_tick_t send_start = rt_tick_get();
        int send_result = socket_send_all(sockfd, http_header, (size_t)header_len);
        if (send_result == 0)
            send_result = socket_send_all(sockfd, audio_buffer, audio_bytes);

        const uint32_t send_ms =
            (uint32_t)((rt_tick_get() - send_start) * 1000 / RT_TICK_PER_SECOND);

        if (send_result == 0)
        {
            LOG_I("audio_send: chunk %d sent %d bytes in %u ms",
                  chunk_index, (int)((size_t)header_len + audio_bytes), send_ms);
            err_streak = 0;
        }
        else
        {
            LOG_W("audio_send: chunk %d send incomplete", chunk_index);
            err_streak++;
        }

        close(sockfd);

        chunk_index++;

        // Pause if too many consecutive failures; otherwise yield briefly
        if (err_streak >= kMaxErrStreak)
        {
            LOG_E("audio_send: %d consecutive errors, pausing %u ms",
                  err_streak, kErrBackoffMs * 5);
            rt_thread_mdelay(kErrBackoffMs * 5);
            err_streak = 0;
        }
        else
        {
            rt_thread_mdelay(10);
        }
    }

    rt_device_close(local_mic_dev);

    LOG_I("audio_send: thread exiting, total chunks sent: %d", chunk_index);
    g_db_running = RT_FALSE;
    g_db_tid = RT_NULL;
}
#endif
/* END NEW */


#define SNORE_THREAD_STACK_SIZE 4096
#define SNORE_THREAD_PRIORITY   18
#define SNORE_THREAD_TICK       10

/* NEW: Small helper to POST a JSON body to the backend.
 * Used for /mock/snore-session/{start,stop} and /mock/snore-heartbeat.
 * Returns 0 on success, negative on failure. Non-blocking on transport errors.
 */
static int post_json_to_backend(const char *path, const char *json_body)
{
    if (!path || !json_body)
        return -1;

    char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
    int backend_port = DB_SEND_TARGET_PORT;
    backend_target_get(DB_SEND_TARGET_IP, DB_SEND_TARGET_PORT,
                       backend_host, sizeof(backend_host), &backend_port);

    const size_t body_len = strlen(json_body);
    char header[256];
    int header_len = snprintf(header, sizeof(header),
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %u\r\n"
        "Connection: close\r\n"
        "\r\n",
        path, backend_host, backend_port, (unsigned)body_len);
    if (header_len <= 0 || header_len >= (int)sizeof(header))
        return -2;

    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        LOG_W("post_json: socket() failed, errno=%d", errno);
        return -3;
    }

    struct sockaddr_in serv_addr;
    memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family      = AF_INET;
    serv_addr.sin_port        = htons(backend_port);
    serv_addr.sin_addr.s_addr = inet_addr(backend_host);

    if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) != 0) {
        LOG_W("post_json: connect %s:%d failed, errno=%d",
              backend_host, backend_port, errno);
        close(sockfd);
        return -4;
    }

    /* Send header + body */
    ssize_t total = 0;
    ssize_t to_send = (ssize_t)header_len + (ssize_t)body_len;
    while (total < to_send) {
        ssize_t n = send(sockfd, header + total, header_len - total, 0);
        if (n > 0) {
            total += n;
            continue;
        }
        if (n < 0) {
            LOG_W("post_json: header send failed, errno=%d", errno);
            close(sockfd);
            return -5;
        }
        break;
    }
    /* Now send the body separately (string literal may be in rodata) */
    ssize_t body_sent = 0;
    while (body_sent < (ssize_t)body_len) {
        ssize_t n = send(sockfd, json_body + body_sent, body_len - body_sent, 0);
        if (n <= 0) {
            LOG_W("post_json: body send failed, errno=%d", errno);
            close(sockfd);
            return -6;
        }
        body_sent += n;
    }
    total += body_sent;

    /* Best-effort: read just the status line so the server sees the request
     * as completed before we close. */
    char resp[128] = {0};
    (void)recv(sockfd, resp, sizeof(resp) - 1, 0);
    close(sockfd);

    LOG_I("post_json: %s sent %d bytes", path, (int)total);
    return 0;
}

/* NEW: Heartbeat thread - sends the latest snore score to the backend
 * every HB_INTERVAL_MS milliseconds.  This keeps the snore board reported
 * as "online" by the dashboard even while the audio-send thread is busy
 * collecting a 10-second clip.
 */
static void heartbeat_thread_entry(void *parameter)
{
    (void)parameter;
    LOG_I("hb: thread started (interval=%d ms)", HB_INTERVAL_MS);

    /* Announce session start so the dashboard flips to "online" immediately */
    post_json_to_backend("/mock/snore-session/start", "{\"source\":\"real_snore_board\"}");

    const rt_tick_t period_ticks = rt_tick_from_millisecond(HB_INTERVAL_MS);
    rt_tick_t next_send = rt_tick_get();

    while (g_hb_running) {
        const rt_tick_t now = rt_tick_get();
        /* Sleep in small slices so the loop can be stopped quickly */
        if ((rt_tick_t)(next_send - now) <= (rt_tick_t)RT_TICK_MAX / 2) {
            rt_thread_mdelay(50);
            continue;
        }
        next_send = now + period_ticks;

        /* Snapshot the latest score under lock */
        float score = 0.0f;
        rt_bool_t detected = RT_FALSE;
        float dbfs = 0.0f;
        rt_bool_t dbfs_valid = RT_FALSE;
        if (g_score_mutex) {
            rt_mutex_take(g_score_mutex, RT_WAITING_FOREVER);
            score = g_latest_score;
            detected = g_latest_detected;
            dbfs = g_latest_dbfs;
            dbfs_valid = g_latest_dbfs_valid;
            rt_mutex_release(g_score_mutex);
        }

        char body[192];
        int body_len = dbfs_valid
            ? snprintf(body, sizeof(body),
                "{\"snore_score\":%.3f,\"snore_detected\":%s,\"dbfs\":%.2f,\"source\":\"real_snore_board\"}",
                score, detected ? "true" : "false", dbfs)
            : snprintf(body, sizeof(body),
                "{\"snore_score\":%.3f,\"snore_detected\":%s,\"dbfs\":null,\"source\":\"real_snore_board\"}",
                score, detected ? "true" : "false");
        if (body_len > 0) {
            (void)post_json_to_backend("/mock/snore-heartbeat", body);
        }
    }

    /* Full stop reports the session end. Capture-only pauses keep this
     * heartbeat alive so Edgi remains online during a voice interaction. */
    post_json_to_backend("/mock/snore-session/stop", "{}");

    LOG_I("hb: thread exiting");
    g_hb_tid = RT_NULL;
}

/* Publish the latest board-side snore data for the heartbeat thread. */
static void publish_latest_score(float score, rt_bool_t detected, float dbfs)
{
    if (!g_score_mutex)
        return;
    rt_mutex_take(g_score_mutex, RT_WAITING_FOREVER);
    g_latest_score = score;
    g_latest_detected = detected ? RT_TRUE : RT_FALSE;
    g_latest_dbfs = dbfs;
    g_latest_dbfs_valid = RT_TRUE;
    rt_mutex_release(g_score_mutex);
}

static void snore_detect_thread_entry(void *parameter)
{
    (void)parameter;

    LOG_I("snore: sliding window started (2s window, hop=%d samples)", (int)kHopSamples);

    if (init_model() != 0)
    {
        LOG_E("snore: init_model failed");
        g_snore_running = RT_FALSE;
        audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);
        g_snore_tid = RT_NULL;
        return;
    }

    leds_init_once();
    led_write(kLedBlue, RT_FALSE);

    static int16_t ring[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    static int16_t snap[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    int16_t mono_frame[512];
    size_t w = 0;
    size_t filled = 0;
    size_t since_last = 0;

    while (g_snore_running)
    {
        const rt_size_t read_size = audio_capture_hub_read(
            AUDIO_CAPTURE_SNORE,
            mono_frame,
            sizeof(mono_frame),
            rt_tick_from_millisecond(100));
        if (read_size == 0)
        {
            continue;
        }

        const size_t total_samples = read_size / sizeof(int16_t);
        for (size_t i = 0; i < total_samples; i++)
        {
            ring[w] = mono_frame[i];
            w = (w + 1) % kInputSamples;
            if (filled < kInputSamples) filled++;
            since_last++;
        }

        /* Non-blocking blue blink handling */
        const rt_tick_t now = rt_tick_get();
        if (g_blue_blink_until != 0 && now < g_blue_blink_until)
        {
            if (now >= g_blue_blink_next_toggle)
            {
                g_blue_blink_on = (g_blue_blink_on == RT_FALSE) ? RT_TRUE : RT_FALSE;
                led_write(kLedBlue, g_blue_blink_on);
                g_blue_blink_next_toggle = now + rt_tick_from_millisecond(50);
            }
        }
        else
        {
            g_blue_blink_until = 0;
            g_blue_blink_on = RT_FALSE;
            led_write(kLedBlue, RT_FALSE);
        }

        if (filled < kInputSamples)
            continue;

        if (since_last < kHopSamples)
            continue;

        since_last = 0;

        /* Snapshot last 2s from ring into linear buffer */
        size_t tail = w; /* w points to next write => oldest is w */
        const size_t n1 = kInputSamples - tail;
        memcpy(&snap[0], &ring[tail], n1 * sizeof(int16_t));
        if (tail != 0)
            memcpy(&snap[n1], &ring[0], tail * sizeof(int16_t));

        /* During "sampling+infer", keep blue off (unless blinking) */
        if (g_blue_blink_until == 0)
            led_write(kLedBlue, RT_FALSE);

        float score = 0.0f;
        rt_bool_t detected = RT_FALSE;
        int ret = snore_infer_from_pcm(snap, &score, &detected);
        if (ret != RT_EOK)
        {
            LOG_W("snore: infer failed (%d)", ret);
            continue;
        }

        const rt_bool_t alarm_allowed =
            audio_capture_hub_is_snore_suppressed() ? RT_FALSE : RT_TRUE;
        const rt_bool_t effective_detected =
            (detected && alarm_allowed) ? RT_TRUE : RT_FALSE;
        const rt_bool_t model_positive =
            score >= kSnoreThreshold ? RT_TRUE : RT_FALSE;
        xiaozhi_ui_set_snore_inference(
            model_positive ? true : false,
            effective_detected ? true : false,
            (model_positive && !alarm_allowed) ? true : false,
            score);
        publish_latest_score(score, effective_detected,
                             calculate_db(snap, kInputSamples));
        if (effective_detected)
        {
            blue_blink_for_ms(1000, 100); // This now calls the function inside the namespace
            xz_trigger_care_alarm();
        }
        else if (detected && !alarm_allowed)
        {
            LOG_I("snore: alert suppressed during local playback");
        }
    }

    LOG_I("snore: detect thread exiting");
    g_snore_tid = RT_NULL;
}

extern "C" {

// These are actually defined as static in this file, but we can access them
// The stop function handles detector cleanup.
// We'll declare these as weak references for xiaozhi_ui.c

int snore_detect_stop(void)
{
    LOG_I("snore_detect_stop: called");
    if (lifecycle_lock() != RT_EOK)
    {
        return -RT_ERROR;
    }

    /* Workers own their device handles and terminate themselves. Never call
     * rt_thread_delete() here: a worker can clear its handle between the
     * null check and delete call, which caused the observed NULL assertion. */
    g_snore_running = RT_FALSE;
    audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);
    g_db_running = RT_FALSE;
    g_hb_running = RT_FALSE;

    leds_init_once();
    led_write(kLedRed, RT_TRUE);
    led_write(kLedGreen, RT_FALSE);
    led_write(kLedBlue, RT_FALSE);

    wait_for_capture_threads(1500);
    wait_for_heartbeat_thread(1500);
    lifecycle_unlock();
    return RT_EOK;
}

int snore_detect_is_running(void)
{
    return g_snore_running ? 1 : 0;
}

int snore_detect_pause_for_voice(void)
{
    LOG_D("snore: shared microphone needs no voice pause");
    return RT_EOK;
}

int snore_detect_start(void)
{
#ifndef RT_USING_AUDIO
    LOG_E("RT_USING_AUDIO not enabled");
    return -RT_ERROR;
#else
    if (lifecycle_lock() != RT_EOK)
    {
        return -RT_ERROR;
    }

    /* A previous stop may still be completing a socket call or device close.
     * Never overwrite a live thread handle with a replacement thread. */
    if (!g_snore_running && (g_snore_tid || g_db_tid))
    {
        wait_for_capture_threads(2500);
    }
    if (!g_hb_running && g_hb_tid)
    {
        wait_for_heartbeat_thread(2500);
    }
    if (g_snore_tid || g_db_tid || (!g_hb_running && g_hb_tid))
    {
        LOG_W("snore: previous workers are still exiting, start deferred");
        lifecycle_unlock();
        return -RT_ERROR;
    }

    if (g_snore_running)
    {
        LOG_I("snore: detect already running");
        lifecycle_unlock();
        return RT_EOK;
    }

    if (init_model() != 0)
    {
        lifecycle_unlock();
        return -RT_ERROR;
    }

    if (audio_capture_hub_init() != RT_EOK ||
        audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE,
                                      RT_TRUE) != RT_EOK)
    {
        LOG_E("snore: shared audio subscriber unavailable");
        lifecycle_unlock();
        return -RT_ERROR;
    }

    leds_init_once();
    // Running: red off, green on, blue off
    led_write(kLedRed, RT_FALSE);
    led_write(kLedGreen, RT_TRUE);
    led_write(kLedBlue, RT_FALSE);

    g_snore_running = RT_TRUE;

    /* NEW: Create score-publish mutex if needed (shared with heartbeat thread) */
    if (!g_score_mutex) {
        g_score_mutex = rt_mutex_create("score_mtx", RT_IPC_FLAG_FIFO);
        if (!g_score_mutex) {
            LOG_E("snore: create score mutex failed");
            g_snore_running = RT_FALSE;
            audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);
            lifecycle_unlock();
            return -RT_ENOMEM;
        }
    }

    g_snore_tid = rt_thread_create("snore_det",
                                  snore_detect_thread_entry,
                                  RT_NULL,
                                  SNORE_THREAD_STACK_SIZE,
                                  SNORE_THREAD_PRIORITY,
                                  SNORE_THREAD_TICK);
    if (!g_snore_tid)
    {
        LOG_E("snore: create thread failed");
        g_snore_running = RT_FALSE;
        audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);
        lifecycle_unlock();
        return -RT_ENOMEM;
    }

    rt_thread_startup(g_snore_tid);

    /* The detector already calculates dBFS and publishes it in the 1 Hz
     * heartbeat. Do not start the legacy 10-second uploader here because it
     * opened mic0 a second time and consumed a large temporary buffer. */
    g_db_running = RT_FALSE;

    /* NEW: Start heartbeat thread so the dashboard flips to "online"
     * immediately and stays online even during the 10-second audio
     * collection phase. The thread announces session start and then
     * pushes a 1Hz snore score to /mock/snore-heartbeat. */
    if (!g_hb_running && !g_hb_tid) {
        g_hb_running = RT_TRUE;
        g_hb_tid = rt_thread_create("snore_hb",
                                    heartbeat_thread_entry,
                                    RT_NULL,
                                    HB_THREAD_STACK_SIZE,
                                    HB_THREAD_PRIORITY,
                                    HB_THREAD_TICK);
        if (!g_hb_tid) {
            LOG_E("snore: create heartbeat thread failed");
            g_hb_running = RT_FALSE;
            g_snore_running = RT_FALSE;
            audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);
            wait_for_capture_threads(1500);
            lifecycle_unlock();
            return -RT_ENOMEM;
        }
        rt_thread_startup(g_hb_tid);
        LOG_I("snore: heartbeat thread started");
    }
    /* END NEW */

    lifecycle_unlock();
    return RT_EOK;
#endif
}

int snore_detect_resume_after_voice(void)
{
    LOG_D("snore: shared microphone remained active during voice");
    return RT_EOK;
}



/* NEW: Function to get dB history */
int snore_get_db_history(float* buffer, int size) {
    if (!buffer || size <= 0 || !g_db_mutex) {
        return -RT_ERROR;
    }

    rt_mutex_take(g_db_mutex, RT_WAITING_FOREVER);

    int copy_count = (size < DB_HISTORY_SIZE) ? size : DB_HISTORY_SIZE;
    // Fix: use positive index to avoid negative modulo issue
    int start_index = g_db_history_index - copy_count;
    if (start_index < 0) start_index += DB_HISTORY_SIZE;

    for (int i = 0; i < copy_count; i++) {
        int src_idx = (start_index + i) % DB_HISTORY_SIZE;
        buffer[i] = g_db_history[src_idx];
    }

    rt_mutex_release(g_db_mutex);

    return copy_count; // Return number of values copied
}
/* END NEW */

} // extern "C"

#ifdef RT_USING_FINSH
/*
 * Debug command: capture ~2s audio and infer once.
 * This is kept for manual testing via MSH and is independent of the sliding-window thread.
 */
static int snore_detect_once(void)
{
#ifndef RT_USING_AUDIO
    LOG_E("RT_USING_AUDIO not enabled");
    return -RT_ERROR;
#else
    if (init_model() != 0)
        return -RT_ERROR;

    if (g_snore_running)
    {
        LOG_W("snore_detect_once: detector is already running");
        return -RT_EBUSY;
    }

    static int16_t pcm[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    if (audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE,
                                      RT_TRUE) != RT_EOK)
    {
        return -RT_ERROR;
    }

    size_t collected = 0;
    while (collected < kInputSamples)
    {
        const rt_size_t read_size = audio_capture_hub_read(
            AUDIO_CAPTURE_SNORE,
            &pcm[collected],
            (kInputSamples - collected) * sizeof(int16_t),
            rt_tick_from_millisecond(200));
        if (read_size == 0)
        {
            continue;
        }
        collected += read_size / sizeof(int16_t);
    }
    audio_capture_hub_set_enabled(AUDIO_CAPTURE_SNORE, RT_FALSE);

    led_write(kLedBlue, RT_FALSE);

    float score = 0.0f;
    rt_bool_t detected = RT_FALSE;
    int ret = snore_infer_from_pcm(pcm, &score, &detected);
    if (ret != RT_EOK)
        return ret;

    xiaozhi_ui_set_snore_result(detected ? true : false, score);
    if (detected)
        blue_blink_for_ms(1000, 100); // This now calls the function inside the namespace

    return RT_EOK;
#endif
}

MSH_CMD_EXPORT(snore_detect_once, Capture mic0 audio and run the snore model once);

/* NEW: FINSH command to get dB history */
static void get_db_history(int argc, char *argv[])
{
    float db_values[DB_HISTORY_SIZE];
    int count = snore_get_db_history(db_values, DB_HISTORY_SIZE);

    if (count < 0) {
        rt_kprintf("Failed to get dB history.\n");
        return;
    }

    rt_kprintf("Last %d dB readings (oldest to newest):\n", count);
    for (int i = 0; i < count; i++) {
        rt_kprintf("  [%2d]: %.2f dB\n", i, db_values[i]);
    }
}
MSH_CMD_EXPORT(get_db_history, Get the last 10 dB readings);
/* END NEW */

/* FINSH command to send audio only (without snore detection). */
static int audio_send_only(void)
{
    rt_kprintf("Raw audio upload is disabled in shared microphone mode.\n");
    return -RT_ENOSYS;
}
MSH_CMD_EXPORT(audio_send_only, Raw audio upload is disabled);

/* NEW: Stop audio send */
static int audio_send_stop(void)
{
    g_db_running = RT_FALSE;
    rt_kprintf("Raw audio upload is not running.\n");
    return RT_EOK;
}
MSH_CMD_EXPORT(audio_send_stop, Stop audio send thread);

#endif
