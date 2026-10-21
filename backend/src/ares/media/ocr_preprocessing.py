from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger("ares.ocr_preprocessing")


def _compute_projection_variance(binary_matrix: list[list[int]]) -> float:
    """Compute variance of horizontal line projections (row sums)."""
    if not binary_matrix:
        return 0.0
    row_sums = [sum(row) for row in binary_matrix]
    n = len(row_sums)
    if n <= 1:
        return 0.0
    mean = sum(row_sums) / n
    variance = sum((x - mean) ** 2 for x in row_sums) / (n - 1)
    return variance


def detect_skew_angle(image: Any, max_angle: float = 15.0, step: float = 0.5) -> float:
    """Estimate page skew angle using horizontal projection profile variance.

    A properly aligned document has high variance across row projections
    because text lines create high peaks and whitespace creates deep troughs.
    """
    try:
        from PIL import Image
    except ImportError:
        return 0.0

    # Downscale for performance during angle sweep
    img = image.convert("L")
    w, h = img.size
    scale = min(1.0, 800.0 / max(w, h, 1))
    if scale < 1.0:
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    # Simple Otsu-like thresholding to binary (text=1, background=0)
    # Most documents are dark text on light background
    get_pixels = getattr(img, "get_flattened_data", None) or img.getdata
    pixels = list(get_pixels())
    if not pixels:
        return 0.0
    threshold = sum(pixels) / len(pixels)
    w, h = img.size

    best_angle = 0.0
    best_variance = -1.0

    num_steps = int((2 * max_angle) / step) + 1
    angles = [-max_angle + i * step for i in range(num_steps)]

    for angle in angles:
        # Rotate binarized representation or small image
        rotated = img.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=255)
        rot_get = getattr(rotated, "get_flattened_data", None) or rotated.getdata
        rot_pixels = list(rot_get())
        rw, rh = rotated.size
        # Row sums
        row_sums = [
            sum(1 for x in range(rw) if rot_pixels[y * rw + x] < threshold)
            for y in range(rh)
        ]
        n = len(row_sums)
        if n <= 1:
            continue
        mean = sum(row_sums) / n
        variance = sum((x - mean) ** 2 for x in row_sums) / (n - 1)

        if variance > best_variance:
            best_variance = variance
            best_angle = angle

    return best_angle


def deskew_image(image_bytes: bytes, max_angle: float = 15.0) -> bytes:
    """Detect skew and rotate image back to horizontal orientation."""
    try:
        from PIL import Image
    except ImportError:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = img.format or "PNG"
            angle = detect_skew_angle(img, max_angle=max_angle)
            if abs(angle) < 0.5:
                return image_bytes  # Negligible skew

            logger.info("Deskewing image by %.1f degrees", -angle)
            # Rotate by -angle to correct
            corrected = img.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
            buffer = io.BytesIO()
            save_fmt = fmt if fmt.upper() in {"PNG", "JPEG"} else "PNG"
            corrected.save(buffer, format=save_fmt)
            return buffer.getvalue()
    except Exception as exc:
        logger.warning("Deskew failed (%s); proceeding with original image", exc)
        return image_bytes


def denoise_image(image_bytes: bytes) -> bytes:
    """Apply median filtering and contrast enhancement to reduce OCR noise."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = img.format or "PNG"
            # Apply light median filter to remove speckle / scan noise
            denoised = img.filter(ImageFilter.MedianFilter(size=3))
            # Enhance contrast for sharper character boundaries
            enhancer = ImageEnhance.Contrast(denoised)
            enhanced = enhancer.enhance(1.35)

            buffer = io.BytesIO()
            save_fmt = fmt if fmt.upper() in {"PNG", "JPEG"} else "PNG"
            enhanced.save(buffer, format=save_fmt)
            return buffer.getvalue()
    except Exception as exc:
        logger.warning("Denoise failed (%s); proceeding with original image", exc)
        return image_bytes


def preprocess_ocr_image(
    image_bytes: bytes,
    *,
    deskew: bool = True,
    denoise: bool = True,
) -> bytes:
    """Chained preprocessing for scanned pages and images prior to OCR inference."""
    result = image_bytes
    if deskew:
        result = deskew_image(result)
    if denoise:
        result = denoise_image(result)
    return result
