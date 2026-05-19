/*
 * Minimal local TFLite Micro inference test (RT-Thread msh).
 *
 * This does NOT capture audio yet. It only verifies the model can be loaded,
 * tensors can be allocated, and one Invoke() succeeds.
 */

#include <rtthread.h>
#include <rtdevice.h>

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "meow.tflm"
#define DBG_LVL DBG_LOG
#include <rtdbg.h>

#include "edge-impulse-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "edge-impulse-sdk/tensorflow/lite/schema/schema_generated.h"

#include "tflite-model/tflite-resolver.h"
#include "tflite-model/snore_model_data.h"

namespace {

// NOTE: Arena is placed in HyperRAM to avoid internal RAM overflow.
// ALIGN() macro comes from Edge Impulse model header and enforces alignment.
// If AllocateTensors(true) fails at runtime, gradually increase this value.
constexpr size_t kTensorArenaSize = 256 * 1024;
ALIGN(16) static uint8_t tensor_arena[kTensorArenaSize] rt_section(".m33_m55_shared_hyperram");

static void dump_tensor_info(const TfLiteTensor *t, const char *name)
{
    if (!t)
    {
        LOG_E("%s tensor is null", name);
        return;
    }

    LOG_I("%s: type=%d, dims=%d", name, (int)t->type, t->dims ? t->dims->size : -1);
    if (t->dims)
    {
        rt_kprintf("%s shape: [", name);
        for (int i = 0; i < t->dims->size; i++)
        {
            rt_kprintf("%d%s", (int)t->dims->data[i], (i == t->dims->size - 1) ? "" : ", ");
        }
        rt_kprintf("]\n");
    }

    if (t->quantization.type == kTfLiteAffineQuantization && t->quantization.params)
    {
        const auto *q = (const TfLiteAffineQuantization *)t->quantization.params;
        const float scale = (q->scale && q->scale->size > 0) ? q->scale->data[0] : 0.0f;
        const int zero_point = (q->zero_point && q->zero_point->size > 0) ? (int)q->zero_point->data[0] : 0;
        LOG_I("%s quant: scale=%f zero_point=%d", name, scale, zero_point);
    }
}

} // namespace

static int meow_model_test(void)
{
    const tflite::Model *model = tflite::GetModel(snore_model_tflite);
    if (!model)
    {
        LOG_E("GetModel failed");
        return -RT_ERROR;
    }

    // Use the project's resolver macro. If your model uses more ops,
    // extend `edge-impulse/tflite-model/tflite-resolver.h`.
    EI_TFLITE_RESOLVER

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);

    TfLiteStatus status = interpreter.AllocateTensors(true);
    if (status != kTfLiteOk)
    {
        LOG_E("AllocateTensors failed status=%d, arena=%d, inputs=%d, outputs=%d",
              status, (int)kTensorArenaSize,
              (int)interpreter.inputs_size(), (int)interpreter.outputs_size());
        return -RT_ERROR;
    }

    TfLiteTensor *input = interpreter.input(0);
    TfLiteTensor *output = interpreter.output(0);

    dump_tensor_info(input, "input0");
    dump_tensor_info(output, "output0");

    // Fill input with zeros to validate an end-to-end Invoke().
    if (input->data.raw && input->bytes > 0)
    {
        rt_memset(input->data.raw, 0, input->bytes);
    }

    status = interpreter.Invoke();
    if (status != kTfLiteOk)
    {
        LOG_E("Invoke failed");
        return -RT_ERROR;
    }

    // Dump first few output values (supports int8/uint8/float).
    const int max_print = 8;
    LOG_I("Invoke OK. Output preview:");
    if (output->type == kTfLiteInt8)
    {
        for (int i = 0; i < max_print && i < (int)output->bytes; i++)
        {
            rt_kprintf(" %d", (int)output->data.int8[i]);
        }
        rt_kprintf("\n");
    }
    else if (output->type == kTfLiteUInt8)
    {
        for (int i = 0; i < max_print && i < (int)output->bytes; i++)
        {
            rt_kprintf(" %u", (unsigned)output->data.uint8[i]);
        }
        rt_kprintf("\n");
    }
    else if (output->type == kTfLiteFloat32)
    {
        const int count = output->bytes / sizeof(float);
        for (int i = 0; i < max_print && i < count; i++)
        {
            rt_kprintf(" %f", output->data.f[i]);
        }
        rt_kprintf("\n");
    }
    else
    {
        LOG_W("Unhandled output type=%d", (int)output->type);
    }

    return RT_EOK;
}

#ifdef RT_USING_FINSH
MSH_CMD_EXPORT(meow_model_test, Run local int8 TFLM model once and print output);
#endif

