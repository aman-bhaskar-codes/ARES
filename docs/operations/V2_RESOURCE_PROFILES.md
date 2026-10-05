# V2 resource profiles

These are starting operating profiles, not guaranteed minimum hardware.

| Profile | Starting host | Admission starting point | Optional capabilities |
|---|---|---|---|
| Lean | 4 CPU / 8 GB RAM / SSD | 1 research run + 1 small media job | browser off; OCR/ASR serialized |
| Standard | 8 CPU / 16 GB RAM / SSD | 2 research runs + 1 heavy media job | 1 browser slot; bounded embedding batches |
| Accelerated | Standard + supported GPU | increase media batch only after load tests | GPU ASR/OCR only when measured |

Native OCR/ASR/ONNX thread pools can oversubscribe a host. Set total thread budgets and measure process RSS, queue wait and API responsiveness under mixed work. Optional workers must not determine API liveness.

Initial admission proposals remain configurable: 10 MB/20 MP images, 20 MB/100-page rich PDFs, 50 MB/10-minute audio, 100 MB/5-minute video with <=60 selected frames, 50k table cells, and a 1 GB workspace asset+derivative ceiling. Limits must be checked against decoded output as well as upload bytes.
