# ????????????????

- ????`D:\STUDY\Snoring Dataset`
- ????150 ???? no_snore=75?snore=75
- ?????`0.6`
- ?????`D:\STUDY\hrrr-radar-monitor-system\models\snore_dataset_light\snore_dataset_light.keras`??? 110759 bytes
- INT8 ???`D:\STUDY\hrrr-radar-monitor-system\models\snore_dataset_light\snore_dataset_light_int8.tflite`??? 13512 bytes
- ???????97247 bytes?? 87.80%

## ??????

| ?? | Float/Keras | INT8/TFLite | INT8-Float | ???? |
|---|---:|---:|---:|---:|
| Accuracy | 0.953333 | 0.953333 | 0.000000 | +0.000% |
| Precision | 0.947368 | 0.947368 | 0.000000 | +0.000% |
| Recall | 0.960000 | 0.960000 | 0.000000 | +0.000% |
| Specificity | 0.946667 | 0.946667 | 0.000000 | +0.000% |
| NPV | 0.959459 | 0.959459 | 0.000000 | +0.000% |
| F1 | 0.953642 | 0.953642 | 0.000000 | +0.000% |
| F0.5 | 0.949868 | 0.949868 | 0.000000 | +0.000% |
| F2 | 0.957447 | 0.957447 | 0.000000 | +0.000% |
| Balanced Acc | 0.953333 | 0.953333 | 0.000000 | +0.000% |
| MCC | 0.906747 | 0.906747 | 0.000000 | +0.000% |
| FPR | 0.053333 | 0.053333 | 0.000000 | +0.000% |
| FNR | 0.040000 | 0.040000 | 0.000000 | +0.000% |
| False Alarm | 0.053333 | 0.053333 | 0.000000 | +0.000% |
| Miss Rate | 0.040000 | 0.040000 | 0.000000 | +0.000% |
| ROC-AUC | 0.987378 | 0.988356 | 0.000978 | +0.099% |

## ????/????

| ?? | Float/Keras | INT8/TFLite | INT8-Float |
|---|---:|---:|---:|
| PR-AUC/AP | 0.982559 | 0.981140 | -0.001418 |
| ROC-AUC(recomputed) | 0.987378 | 0.988356 | +0.000978 |
| Brier Score | 0.036689 | 0.037933 | +0.001244 |
| LogLoss | 0.171401 | 0.138479 | -0.032923 |
| Mean score(snore) | 0.961905 | 0.958958 | -0.002946 |
| Mean score(no_snore) | 0.061542 | 0.063698 | +0.002156 |
| Median score(snore) | 0.999934 | 0.996094 | -0.003840 |
| Median score(no_snore) | 0.001181 | 0.000000 | -0.001181 |

## ?????

- ????????0.003320
- ????????0.002531
- ????????0.062173
- Pearson ???0.999877
- Spearman ???0.905539

## ????

- Float/Keras?TN=71, FP=4, FN=3, TP=72
- INT8/TFLite?TN=71, FP=4, FN=3, TP=72

## ??

- INT8 ?????? Accuracy?Precision?Recall?F1?Specificity?MCC ?????????????????
- ROC-AUC ? 0.987378 ? 0.988356?AP/PR-AUC ? 0.982559 ? 0.981140???????
- Brier Score ? LogLoss ????????????????????????????? 0.6 ?????????
- ????? 110759 bytes ?? 13512 bytes???? 87.80%?????? Xiaozhi M55 ????

## ??

- `quantization_metrics_comparison.png`
- `quantization_metric_delta.png`
- `quantization_confusion_matrices.png`
- `quantization_score_agreement.png`