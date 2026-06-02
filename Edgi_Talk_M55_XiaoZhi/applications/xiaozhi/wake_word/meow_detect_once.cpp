/*
 * Capture microphone audio and run local meow detector model once.
 */

#include <rtthread.h>
#include <rtdevice.h>
#include <board.h>
#include <string.h>

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "meow.det"
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
#define PI 3.14159265358979323846f

/* Audio device name */
#ifndef BSP_XIAOZHI_MIC_DEVICE_NAME
#define BSP_XIAOZHI_MIC_DEVICE_NAME "mic0"
#endif

/* --- NEW: Configuration for DB sending --- */
#ifndef DB_SEND_TARGET_IP
#define DB_SEND_TARGET_IP "10.160.50.41"  // Replace with your target IP
#endif

#ifndef DB_SEND_TARGET_PORT
#define DB_SEND_TARGET_PORT 8081           // Replace with your target port
#endif

#define DB_HISTORY_SIZE 10                 // Store 10 seconds of dB readings
#define DB_THREAD_STACK_SIZE 2048
#define DB_THREAD_PRIORITY 17  // Higher than main meow thread (18)
#define DB_THREAD_TICK 10
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

// Snore model: input [1,60,20] = 1200 bytes (Mel spectrogram features)
// Quant params from model export
constexpr float kInScale = 0.01948132f;
constexpr int kInZeroPoint = 24;
constexpr float kOutScale = 0.00390625f;
constexpr int kOutZeroPoint = -128;

// DSP params for feature extraction
constexpr int kFFTSize = 512;
constexpr int kFFTOutputSize = 257;  // FFT size / 2 + 1
constexpr int kHopSize = 256;        // 16ms hop @ 16kHz
constexpr int kNumFrames = 60;       // frames to accumulate (match model)
constexpr int kMelBins = 20;         // output mel bins
constexpr int kFeatureSize = 60 * 20; // 1200

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
static rt_thread_t g_meow_tid = RT_NULL;
static volatile rt_bool_t g_meow_running = RT_FALSE;
static rt_thread_t g_db_tid = RT_NULL; // NEW: Thread handle for dB detection
static volatile rt_bool_t g_db_running = RT_FALSE; // NEW: Flag for dB thread
static rt_device_t g_mic_dev = RT_NULL;
static rt_tick_t g_last_db_send_tick = 0; // NEW: Track last send time
static float g_db_history[DB_HISTORY_SIZE] rt_section(".m33_m55_shared_hyperram"); // NEW: Ring buffer for dB history
static int g_db_history_index = 0; // NEW: Index for the ring buffer
static rt_mutex_t g_db_mutex = RT_NULL; // NEW: Mutex to protect access to history and index

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
    /* Mel scale: f_mel = 2595 * log10(1 + f/700) */
    const float freq_to_mel = 2595.0f;
    const float sample_rate = (float)kSampleRate;
    const int n_fft = kFFTSize;
    const int n_bins = kFFTOutputSize;  // 257

    /* Convert bin index to frequency */
    auto bin_to_freq = [sample_rate, n_fft](int bin) {
        return (float)bin * sample_rate / n_fft;
    };
    /* Convert frequency to mel */
    auto freq_to_mel_fn = [freq_to_mel](float freq) {
        return freq_to_mel * log10f(1.0f + freq / 700.0f);
    };
    /* Convert mel to frequency */
    auto mel_to_freq_fn = [freq_to_mel](float mel) {
        return 700.0f * (powf(10.0f, mel / freq_to_mel) - 1.0f);
    };

    const float f_low = 0.0f;
    const float f_high = sample_rate / 2.0f;
    const float mel_low = freq_to_mel_fn(f_low);
    const float mel_high = freq_to_mel_fn(f_high);
    const float mel_step = (mel_high - mel_low) / (kMelBins + 1);

    for (int m = 0; m < kMelBins; m++) {
        float mel_center = mel_low + (m + 1) * mel_step;
        float mel_left = mel_center - mel_step;
        float mel_right = mel_center + mel_step;

        float f_left = mel_to_freq_fn(mel_left);
        float f_center = mel_to_freq_fn(mel_center);
        float f_right = mel_to_freq_fn(mel_right);

        for (int k = 0; k < n_bins; k++) {
            float f = bin_to_freq(k);
            float w = 0.0f;

            if (f >= f_left && f < f_center) {
                w = (f - f_left) / (f_center - f_left);
            } else if (f >= f_center && f <= f_right) {
                w = (f_right - f) / (f_right - f_center);
            }

            g_mel_weights[m][k] = w;
        }
    }

    LOG_I("Mel weights computed for %d filters x %d bins", kMelBins, n_bins);
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
    LOG_I("init_model: quant scale=%.6f zp=%d", g_input_scale, g_input_zero_point);

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

static void pcm16_to_int8(const int16_t *pcm, int8_t *dst, size_t n)
{
    for (size_t i = 0; i < n; i++)
    {
        // int16 -> float [-1, 1)
        const float x = (float)pcm[i] / 32768.0f;
        const int32_t q = (int32_t)(x / kInScale + (float)kInZeroPoint);
        dst[i] = clamp_i8(q);
    }
}

/* ================================================================
 *  Compute one Mel spectrogram frame (20 bins) from 512 samples
 * ================================================================ */
static void compute_mel_spectrum(const float *samples_512, float *mel_out)
{
    /* Apply Hann window */
    for (int i = 0; i < kFFTSize; i++) {
        float w = 0.5f * (1.0f - cosf(2.0f * PI * i / (kFFTSize - 1)));
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
        /* Log output: ln(sum + eps) */
        float v = logf(sum + 1e-6f);
        /* Clip to reasonable range */
        if (v < -10.0f) v = -10.0f;
        if (v > 2.0f) v = 2.0f;
        mel_out[m] = v;
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

static int meow_infer_from_pcm(const int16_t *pcm, float *out_score, rt_bool_t *out_detected)
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

    /* ── Extract Mel spectrogram from PCM ───────────────────────── */
    /*
     *  Frame 0  : pcm[0       .. 511]
     *  Frame 1  : pcm[256     .. 767]
     *  ...
     *  Total needed: 60 frames (model expects [1,60,20,1])
     *
     *  PCM total: 32000 samples (2 sec @ 16kHz)
     *  With hop=256: max frames = (32000-512)/256 + 1 = 125 frames
     */
    const int max_frames = (int)kInputSamples - kFFTSize + 1;
    const int frames_per_block = max_frames / kHopSize;  // ~124 frames available

    /* Process first kFeatureFrames frames from PCM */
    for (int f = 0; f < kFeatureFrames; f++) {
        int offset = f * kHopSize;
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

    // Model output: [1,2] - class 0: unlabelled, class 1: snore, class 2: noise
    // Use class 1 (snore) probability
    const int8_t out0 = g_out->data.int8[0];
    const int8_t out1 = g_out->data.int8[1];
    const float snore_score = ((int)out1 - kOutZeroPoint) * kOutScale;

    // LOG_I("infer: output[0]=%d, output[1]=%d, snore=%.3f",
    //       (int)out0, (int)out1, snore_score);

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

/* NEW: Thread to send raw audio via HTTP continuously
 *  - Collects 10s chunks from the mic
 *  - POSTs each chunk to the backend as soon as it is ready
 *  - Loops until g_db_running is cleared (by meow_detect_stop / audio_send_stop)
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
        char *http_request = (char *)rt_malloc((size_t)collected * 2 + 256);
        if (!http_request)
        {
            LOG_E("audio_send: malloc failed (need %d bytes), backing off",
                  (int)((size_t)collected * 2 + 256));
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        int req_len = snprintf(http_request, 256,
            "POST /audio HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Content-Type: audio/wav\r\n"
            "Content-Length: %d\r\n"
            "Connection: close\r\n"
            "\r\n",
            DB_SEND_TARGET_IP, DB_SEND_TARGET_PORT, (int)((size_t)collected * 2));

        memcpy(http_request + req_len, audio_buffer, (size_t)collected * 2);

        int sockfd = socket(AF_INET, SOCK_STREAM, 0);
        if (sockfd < 0)
        {
            LOG_E("audio_send: socket() failed, errno=%d", errno);
            rt_free(http_request);
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        struct sockaddr_in serv_addr;
        memset(&serv_addr, 0, sizeof(serv_addr));
        serv_addr.sin_family      = AF_INET;
        serv_addr.sin_port        = htons(DB_SEND_TARGET_PORT);
        serv_addr.sin_addr.s_addr = inet_addr(DB_SEND_TARGET_IP);

        if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) != 0)
        {
            LOG_E("audio_send: connect %s:%d failed, errno=%d",
                  DB_SEND_TARGET_IP, DB_SEND_TARGET_PORT, errno);
            close(sockfd);
            rt_free(http_request);
            err_streak++;
            rt_thread_mdelay(kErrBackoffMs);
            continue;
        }

        ssize_t total_sent = 0;
        ssize_t to_send    = (ssize_t)req_len + (ssize_t)((size_t)collected * 2);
        const rt_tick_t send_start = rt_tick_get();
        while (total_sent < to_send)
        {
            ssize_t sent = send(sockfd, http_request + total_sent, to_send - total_sent, 0);
            if (sent < 0)
            {
                LOG_E("audio_send: send failed, errno=%d", errno);
                break;
            }
            total_sent += sent;
        }

        const uint32_t send_ms =
            (uint32_t)((rt_tick_get() - send_start) * 1000 / RT_TICK_PER_SECOND);

        if (total_sent == to_send)
        {
            LOG_I("audio_send: chunk %d sent %d bytes in %u ms",
                  chunk_index, (int)total_sent, send_ms);
            err_streak = 0;
        }
        else
        {
            LOG_W("audio_send: chunk %d partial send %d/%d bytes",
                  chunk_index, (int)total_sent, (int)to_send);
            err_streak++;
        }

        close(sockfd);
        rt_free(http_request);

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
/* END NEW */


#define MEOW_THREAD_STACK_SIZE 4096
#define MEOW_THREAD_PRIORITY   18
#define MEOW_THREAD_TICK       10

static void meow_detect_thread_entry(void *parameter)
{
    (void)parameter;

    LOG_I("meow: sliding window started (2s window, hop=%d samples)", (int)kHopSamples);

    if (init_model() != 0)
    {
        LOG_E("meow: init_model failed");
        g_meow_running = RT_FALSE;
        g_meow_tid = RT_NULL;
        return;
    }

    leds_init_once();
    led_write(kLedBlue, RT_FALSE);

    g_mic_dev = rt_device_find(BSP_XIAOZHI_MIC_DEVICE_NAME);
    if (!g_mic_dev)
    {
        LOG_E("meow: cannot find audio device '%s'", BSP_XIAOZHI_MIC_DEVICE_NAME);
        g_meow_running = RT_FALSE;
        g_meow_tid = RT_NULL;
        return;
    }

    if (rt_device_open(g_mic_dev, RT_DEVICE_FLAG_RDONLY) != RT_EOK)
    {
        LOG_E("meow: cannot open audio device");
        g_mic_dev = RT_NULL;
        g_meow_running = RT_FALSE;
        g_meow_tid = RT_NULL;
        return;
    }

    static int16_t ring[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    static int16_t snap[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    int16_t pdm_frame[PDM_FRAME_SAMPLES];
    size_t w = 0;
    size_t filled = 0;
    size_t since_last = 0;

    while (g_meow_running)
    {
        const rt_size_t read_size = rt_device_read(g_mic_dev, 0, pdm_frame, PDM_FRAME_SIZE);
        if (read_size == 0)
        {
            /* keep UI responsive and allow quick stop */
            rt_thread_mdelay(1);
            continue;
        }

        const size_t total_samples = read_size / sizeof(int16_t);
#if PDM_IS_STEREO
        const size_t mono_samples = total_samples / 2;
        for (size_t i = 0; i < mono_samples; i++)
        {
            ring[w] = pdm_frame[i * 2 + 1];
            w = (w + 1) % kInputSamples;
            if (filled < kInputSamples) filled++;
            since_last++;
        }
#else
        for (size_t i = 0; i < total_samples; i++)
        {
            ring[w] = pdm_frame[i];
            w = (w + 1) % kInputSamples;
            if (filled < kInputSamples) filled++;
            since_last++;
        }
#endif

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
        int ret = meow_infer_from_pcm(snap, &score, &detected);
        if (ret != RT_EOK)
        {
            LOG_W("meow: infer failed (%d)", ret);
            continue;
        }

        xiaozhi_ui_set_meow_result(detected ? true : false, score);
        if (detected)
        {
            blue_blink_for_ms(1000, 100); // This now calls the function inside the namespace
        }
    }

    if (g_mic_dev)
    {
        rt_device_close(g_mic_dev);
        g_mic_dev = RT_NULL;
    }

    LOG_I("meow: detect thread exiting");
    g_meow_tid = RT_NULL;
}

extern "C" {

// These are actually defined as static in this file, but we can access them
// The meow_detect_stop function handles cleanup properly
// We'll declare these as weak references for xiaozhi_ui.c

int meow_detect_stop(void)
{
    LOG_I("meow_detect_stop: called");
    /* Idempotent stop: always force LED state to "stopped" */
    g_meow_running = RT_FALSE;
    g_db_running = RT_FALSE;  // Also stop audio thread

    // Stopped: red on, green off, blue off
    leds_init_once();
    led_write(kLedRed, RT_TRUE);
    led_write(kLedGreen, RT_FALSE);
    led_write(kLedBlue, RT_FALSE);

    /* Close global mic device if open */
    if (g_mic_dev) {
        LOG_I("meow_detect_stop: closing global mic device");
        rt_device_close(g_mic_dev);
        g_mic_dev = RT_NULL;
    }

    /* NEW: Stop DB thread when main detection stops */
    if (g_db_tid) {
        LOG_I("meow_detect_stop: deleting audio thread");
        rt_thread_delete(g_db_tid);
        g_db_tid = RT_NULL;
    }

    /* Give main thread time to exit; no hard join API on RT-Thread */
    rt_thread_mdelay(50);
    return RT_EOK;
}

int meow_detect_start(void)
{
#ifndef RT_USING_AUDIO
    LOG_E("RT_USING_AUDIO not enabled");
    return -RT_ERROR;
#else
    if (g_meow_running)
    {
        LOG_I("meow: detect already running");
        return RT_EOK;
    }

    if (init_model() != 0)
    {
        return -RT_ERROR;
    }

    leds_init_once();
    // Running: red off, green on, blue off
    led_write(kLedRed, RT_FALSE);
    led_write(kLedGreen, RT_TRUE);
    led_write(kLedBlue, RT_FALSE);

    g_meow_running = RT_TRUE;

    g_meow_tid = rt_thread_create("meow_det",
                                  meow_detect_thread_entry,
                                  RT_NULL,
                                  MEOW_THREAD_STACK_SIZE,
                                  MEOW_THREAD_PRIORITY,
                                  MEOW_THREAD_TICK);
    if (!g_meow_tid)
    {
        LOG_E("meow: create thread failed");
        g_meow_running = RT_FALSE;
        return -RT_ENOMEM;
    }

    rt_thread_startup(g_meow_tid);

    /* NEW: Start DB thread when main detection starts */
    if (!g_db_running && !g_db_tid) {
        // Create mutex if it doesn't exist
        if (!g_db_mutex) {
            g_db_mutex = rt_mutex_create("db_mtx", RT_IPC_FLAG_FIFO);
            if (!g_db_mutex) {
                LOG_E("meow: create mutex failed");
                // Stop the meow thread if mutex creation fails
                meow_detect_stop(); // Now correctly calls the function defined below within extern "C"
                return -RT_ENOMEM;
            }
        }

        g_db_running = RT_TRUE;

        g_db_tid = rt_thread_create("db_det_snd",
                                    audio_send_thread_entry,
                                    RT_NULL,
                                    DB_THREAD_STACK_SIZE,
                                    DB_THREAD_PRIORITY,
                                    DB_THREAD_TICK);
        if (!g_db_tid)
        {
            LOG_E("meow: create db thread failed");
            g_db_running = RT_FALSE;
            // Stop the meow thread if db thread creation fails
            meow_detect_stop(); // Now correctly calls the function defined below within extern "C"
            return -RT_ENOMEM;
        }

        rt_thread_startup(g_db_tid);
        LOG_I("meow: db thread started alongside main detection");
    }
    /* END NEW */

    return RT_EOK;
#endif
}



/* NEW: Function to get dB history */
int meow_get_db_history(float* buffer, int size) {
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
static int meow_detect_once(void)
{
#ifndef RT_USING_AUDIO
    LOG_E("RT_USING_AUDIO not enabled");
    return -RT_ERROR;
#else
    if (init_model() != 0)
        return -RT_ERROR;

    rt_device_t dev = rt_device_find(BSP_XIAOZHI_MIC_DEVICE_NAME);
    if (!dev)
    {
        LOG_E("Cannot find audio device '%s'", BSP_XIAOZHI_MIC_DEVICE_NAME);
        return -RT_ERROR;
    }

    if (rt_device_open(dev, RT_DEVICE_FLAG_RDONLY) != RT_EOK)
    {
        LOG_E("Cannot open audio device");
        return -RT_ERROR;
    }

    static int16_t pcm[kInputSamples] rt_section(".m33_m55_shared_hyperram");
    int16_t pdm_frame[PDM_FRAME_SAMPLES];

    size_t collected = 0;
    while (collected < kInputSamples)
    {
        const rt_size_t read_size = rt_device_read(dev, 0, pdm_frame, PDM_FRAME_SIZE);
        if (read_size == 0)
        {
            rt_thread_mdelay(1);
            continue;
        }

        const size_t total_samples = read_size / sizeof(int16_t);
#if PDM_IS_STEREO
        const size_t mono_samples = total_samples / 2;
        for (size_t i = 0; i < mono_samples && collected < kInputSamples; i++)
        {
            pcm[collected++] = pdm_frame[i * 2 + 1]; // right channel
        }
#else
        for (size_t i = 0; i < total_samples && collected < kInputSamples; i++)
        {
            pcm[collected++] = pdm_frame[i];
        }
#endif
    }

    rt_device_close(dev);

    led_write(kLedBlue, RT_FALSE);

    float score = 0.0f;
    rt_bool_t detected = RT_FALSE;
    int ret = meow_infer_from_pcm(pcm, &score, &detected);
    if (ret != RT_EOK)
        return ret;

    xiaozhi_ui_set_meow_result(detected ? true : false, score);
    if (detected)
        blue_blink_for_ms(1000, 100); // This now calls the function inside the namespace

    return RT_EOK;
#endif
}

MSH_CMD_EXPORT(meow_detect_once, Capture mic0 audio (32000 samples) and run meow model once);

/* NEW: FINSH command to get dB history */
static void get_db_history(int argc, char *argv[])
{
    float db_values[DB_HISTORY_SIZE];
    int count = meow_get_db_history(db_values, DB_HISTORY_SIZE);

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

/* NEW: FINSH command to send audio only (without meow detection) */
static int audio_send_only(void)
{
    if (g_db_running) {
        rt_kprintf("Audio send already running\n");
        return -RT_ERROR;
    }

    if (init_model() != 0) {
        return -RT_ERROR;
    }

    g_db_running = RT_TRUE;

    g_db_tid = rt_thread_create("audio_snd",
                                audio_send_thread_entry,
                                RT_NULL,
                                DB_THREAD_STACK_SIZE,
                                DB_THREAD_PRIORITY,
                                DB_THREAD_TICK);
    if (!g_db_tid)
    {
        LOG_E("audio: create thread failed");
        g_db_running = RT_FALSE;
        return -RT_ENOMEM;
    }

    rt_thread_startup(g_db_tid);
    rt_kprintf("Audio send started (without meow detection)\n");
    return RT_EOK;
}
MSH_CMD_EXPORT(audio_send_only, Continuously send mic audio (10s chunks) via HTTP without meow detection);

/* NEW: Stop audio send */
static int audio_send_stop(void)
{
    if (g_db_running) {
        g_db_running = RT_FALSE;
        if (g_db_tid) {
            rt_thread_mdelay(100);
            if (g_db_tid) {
                rt_thread_delete(g_db_tid);
                g_db_tid = RT_NULL;
            }
        }
        rt_kprintf("Audio send stopped\n");
    }
    return RT_EOK;
}
MSH_CMD_EXPORT(audio_send_stop, Stop audio send thread);

#endif
