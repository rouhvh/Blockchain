"""Simple webcam capture helper for building the drowsiness dataset.

Usage:
  python capture_dataset.py --out dataset

Controls while running:
  Keys 1-4 : switch class (1=open,2=closed,3=yawning,4=distracted)
  SPACE    : capture current frame into selected class
  q or ESC : quit

Saved files: dataset/<class>/YYYYMMDD_HHMMSS_millis.jpg
"""

import argparse
import cv2
import os
import time
from pathlib import Path

CLASS_KEYS = {
    ord('1'): 'open',
    ord('2'): 'closed',
    ord('3'): 'yawning',
    ord('4'): 'distracted'
}


def ensure_dirs(root: Path, classes):
    for c in classes:
        (root / c).mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='dataset', help='Output dataset root folder')
    parser.add_argument('--cam', type=int, default=0, help='Webcam device index')
    args = parser.parse_args()

    out = Path(args.out)
    classes = ['open', 'closed', 'yawning', 'distracted']
    ensure_dirs(out, classes)

    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        print('Cannot open webcam', args.cam)
        return

    current_class = 'open'
    counts = {c: len(list((out / c).glob('*.jpg'))) for c in classes}

    print('Capture helper started. Press 1-4 to choose class, SPACE to save, q to quit.')

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        h, w = frame.shape[:2]
        status_text = f'Class={current_class}  Counts=' + ','.join(f'{c}:{counts[c]}' for c in classes)
        cv2.putText(frame, status_text, (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
        cv2.imshow('capture', frame)

        k = cv2.waitKey(1) & 0xFF
        if k == 27 or k == ord('q'):
            break
        if k in CLASS_KEYS:
            current_class = CLASS_KEYS[k]
            print('Switched to', current_class)
        if k == ord(' '):
            ts = time.strftime('%Y%m%d_%H%M%S')
            ms = int(time.time() * 1000) % 1000
            name = f'{ts}_{ms}.jpg'
            path = out / current_class / name
            cv2.imwrite(str(path), frame)
            counts[current_class] += 1
            print('Saved', path)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
