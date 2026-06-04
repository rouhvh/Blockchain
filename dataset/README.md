Dataset for Smart Traffic Safety drowsiness model.

Folders:
- open: images with eyes open / attentive
- closed: images with eyes closed
- yawning: images showing yawning
- distracted: images looking away / phone use

Guidelines:
- 640x480 or higher, consistent lighting where possible
- Aim for at least 500 images per class for good transfer learning
- Use `capture_dataset.py` to collect images from webcam

Preprocessing:
- Images will be resized by the training script to the requested `--img-size`
- Keep similar framing (face centered) for best results
