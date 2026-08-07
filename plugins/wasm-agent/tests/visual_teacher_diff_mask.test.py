import importlib.util
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "visual_teacher_diff_mask.py"
SPEC = importlib.util.spec_from_file_location("visual_teacher_diff_mask", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class VisualTeacherDiffMaskTests(unittest.TestCase):
    def test_reviewer_roi_excludes_unrelated_drift(self):
        target = Image.new("RGB", (100, 100), "white")
        source = target.copy()
        draw = ImageDraw.Draw(source)
        draw.rectangle((10, 60, 30, 80), fill="black")
        draw.rectangle((70, 10, 90, 30), fill="black")

        mask = MODULE.difference_mask(
            source,
            target,
            threshold=24,
            dilation=1,
            minimum_area=16,
            include_boxes=[(0.0, 0.5, 0.5, 1.0)],
        )

        self.assertEqual(mask.getpixel((20, 70))[3], 0)
        self.assertEqual(mask.getpixel((80, 20))[3], 255)


if __name__ == "__main__":
    unittest.main()
