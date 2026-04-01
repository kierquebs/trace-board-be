"""
Unit tests for apps/boards/parsers/geometry.py

All coordinates in mils. No fixtures required — pure computation tests.
"""
import math
import pytest

from apps.boards.parsers.geometry import compute_part_geometry


class TestSinglePin:
    def test_single_pin_returns_geometry(self):
        geom = compute_part_geometry("TP1", [(500, 500)])
        assert geom is not None

    def test_single_pin_angle_is_zero(self):
        geom = compute_part_geometry("TP1", [(500, 500)])
        assert geom.angle_deg == 0.0

    def test_single_pin_center(self):
        geom = compute_part_geometry("TP1", [(500, 500)])
        assert geom.center_x == 500.0
        assert geom.center_y == 500.0

    def test_single_pin_outline_has_four_corners(self):
        geom = compute_part_geometry("TP1", [(500, 500)])
        assert len(geom.outline) == 4

    def test_all_same_position_treated_as_single_pin(self):
        geom = compute_part_geometry("C1", [(100, 200), (100, 200)])
        assert geom is not None
        assert geom.center_x == 100.0
        assert geom.center_y == 200.0


class TestEmptyPins:
    def test_no_pins_returns_none(self):
        geom = compute_part_geometry("U1", [])
        assert geom is None


class TestTwoPinPassives:
    def test_c7863_rotation_45_degrees(self):
        """C7863 on A2141 — pins at (8569,1102) and (8583,1116) → 45°."""
        geom = compute_part_geometry("C7863", [(8569, 1102), (8583, 1116)])
        assert geom is not None
        assert abs(geom.angle_deg - 45.0) < 0.1
        assert abs(geom.center_x - 8576.0) < 0.1
        assert abs(geom.center_y - 1109.0) < 0.1
        assert len(geom.outline) == 4

    def test_horizontal_resistor_0_degrees(self):
        geom = compute_part_geometry("R100", [(100, 200), (130, 200)])
        assert geom is not None
        assert abs(geom.angle_deg - 0.0) < 0.1

    def test_vertical_capacitor_90_degrees(self):
        geom = compute_part_geometry("C200", [(500, 100), (500, 130)])
        assert geom is not None
        assert abs(geom.angle_deg - 90.0) < 0.1

    def test_center_is_midpoint(self):
        geom = compute_part_geometry("R1", [(0, 0), (100, 0)])
        assert geom is not None
        assert abs(geom.center_x - 50.0) < 0.1
        assert abs(geom.center_y - 0.0) < 0.1

    def test_outline_has_four_corners(self):
        geom = compute_part_geometry("C1", [(0, 0), (30, 0)])
        assert len(geom.outline) == 4

    def test_width_includes_pad_radius(self):
        """0402 (distance ~30 mils) → pin_radius=10 → width = 30 + 20 = 50."""
        geom = compute_part_geometry("R1", [(0, 0), (30, 0)])
        assert geom.width > 30.0

    def test_diode_dispatched_as_two_pin(self):
        geom = compute_part_geometry("D1", [(0, 0), (100, 0)])
        assert geom is not None
        assert abs(geom.angle_deg - 0.0) < 0.1

    def test_fuse_dispatched_as_two_pin(self):
        geom = compute_part_geometry("F1", [(0, 0), (100, 0)])
        assert geom is not None

    def test_large_inductor_uses_special_arm(self):
        """L with distance > 50 → army = distance/2, armx = 15."""
        geom = compute_part_geometry("L1", [(0, 0), (100, 0)])
        assert geom is not None
        # height = 2 * army = 2 * 50 = 100
        assert abs(geom.height - 100.0) < 0.5

    def test_three_pin_passive_uses_first_and_last(self):
        """For ≤3 pins prefix C/R/L/D/F, first and last pins define orientation."""
        geom = compute_part_geometry("R1", [(0, 0), (50, 0), (100, 0)])
        assert geom is not None
        assert abs(geom.angle_deg - 0.0) < 0.1


class TestMultiPinIC:
    def test_multi_pin_ic_has_geometry(self):
        pins = [(0, 0), (100, 0), (100, 50), (0, 50)]
        geom = compute_part_geometry("U1", pins)
        assert geom is not None
        assert geom.angle_deg >= 0.0
        assert len(geom.outline) == 4

    def test_ic_center_near_centroid(self):
        pins = [(0, 0), (100, 0), (100, 100), (0, 100)]
        geom = compute_part_geometry("U1", pins)
        assert abs(geom.center_x - 50.0) < 5.0
        assert abs(geom.center_y - 50.0) < 5.0

    def test_ic_width_and_height_nonzero(self):
        pins = [(0, 0), (100, 0), (100, 50), (0, 50)]
        geom = compute_part_geometry("U1", pins)
        assert geom.width > 0
        assert geom.height > 0

    def test_transistor_three_pins_goes_to_ic_path(self):
        """Q prefix with 3 pins falls to multi-pin IC path (not two-pin passive)."""
        geom = compute_part_geometry("Q1", [(0, 0), (50, 0), (25, 50)])
        assert geom is not None
        assert len(geom.outline) == 4

    def test_collinear_pins_handled(self):
        """All pins on one line — hull has only 2 points."""
        geom = compute_part_geometry("U1", [(0, 0), (50, 0), (100, 0), (150, 0)])
        assert geom is not None
        assert len(geom.outline) == 4

    def test_large_ic_many_pins(self):
        """Many pins arranged in a rectangular grid."""
        pins = [(x * 20, y * 20) for x in range(5) for y in range(8)]
        geom = compute_part_geometry("U100", pins)
        assert geom is not None
        assert geom.width > 0
        assert geom.height > 0
        assert len(geom.outline) == 4

    def test_geometry_is_none_for_empty(self):
        assert compute_part_geometry("U1", []) is None

    def test_four_pin_prefix_u_goes_to_ic_path(self):
        """U prefix with ≥4 pins should always use IC path."""
        pins = [(0, 0), (100, 0), (100, 100), (0, 100)]
        geom = compute_part_geometry("U50", pins)
        assert geom is not None
        assert len(geom.outline) == 4
