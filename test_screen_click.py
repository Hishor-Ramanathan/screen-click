"""Self-check for the coordinate maths: python test_screen_click.py"""
from screen_click import to_fraction, to_point

assert to_point({"point_2d": [10, 20]}) == (10, 20)
assert to_point({"bbox_2d": [0, 0, 100, 50], "label": "x"}) == (50, 25)
assert to_point({"x": [30, 40], "y": [40]}) == (30, 40)  # point stuffed under "x"
assert to_fraction(500, 250, 1280, 720, "norm1000") == (0.5, 0.25)
assert to_fraction(640, 360, 1280, 720, "pixels") == (0.5, 0.5)
print("ok")
