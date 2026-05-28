"""Self-contained tests for entry_price_calculator. Run:
    source ~/.zprofile && cd pipeline/06_synthesis && python3 test_entry_price_calculator.py
"""

from entry_price_calculator import compute_entry_price, ARCHETYPE_MIN_RR

# Reference fixture: bull=120, bear=90 -> X = (120 + 180)/3 = 100.0


def test_in_band_favorable():
    r = compute_entry_price(120, 90, 95, "long_term_compounder")
    assert r.case_label == "IN_BAND"
    assert r.entry_price == 95
    assert r.entry_range == {"low": 95, "high": 100}
    assert r.ratio_at_current == 5.0
    assert r.price_gate_passed is True


def test_in_band_boundary_ratio_exactly_2():
    r = compute_entry_price(120, 90, 100, "deep_value")  # C == X
    assert r.case_label == "IN_BAND"
    assert r.ratio_at_current == 2.0
    assert r.entry_price == 100
    assert r.entry_range == {"low": 100, "high": 100}
    assert r.price_gate_passed is True


def test_above_band_deep_value_fails_gate():
    r = compute_entry_price(120, 90, 110, "deep_value")
    assert r.case_label == "ABOVE_BAND"
    assert r.entry_price == 100          # disciplined 2:1 target, not current
    assert r.entry_range == {"low": 97, "high": 103}
    assert r.ratio_at_current == 0.5
    assert r.price_gate_passed is False  # 0.5 < 2.0


def test_above_band_compounder_passes_gate():
    r = compute_entry_price(120, 90, 101, "quality_compounder")
    assert r.case_label == "ABOVE_BAND"
    assert round(r.ratio_at_current, 3) == 1.727
    assert r.price_gate_passed is True   # 1.727 >= 1.5


def test_same_price_different_archetype_different_gate():
    qc = compute_entry_price(120, 90, 101, "quality_compounder")
    dv = compute_entry_price(120, 90, 101, "deep_value")
    assert qc.price_gate_passed is True
    assert dv.price_gate_passed is False


def test_below_bear_at_floor():
    r = compute_entry_price(120, 90, 90, "long_term_compounder")  # C == bear
    assert r.case_label == "BELOW_BEAR"
    assert r.entry_price == 90
    assert r.entry_range == {"low": 90, "high": 100}  # high = 2:1 price X
    assert r.ratio_at_current is None    # undefined at/below bear
    assert r.price_gate_passed is True


def test_below_bear_under_floor():
    r = compute_entry_price(120, 90, 80, "deep_value")
    assert r.case_label == "BELOW_BEAR"
    assert r.entry_price == 80
    assert r.entry_range == {"low": 80, "high": 100}
    assert r.price_gate_passed is True


def test_inverted_at_bull():
    r = compute_entry_price(120, 90, 120, "long_term_compounder")  # C == bull
    assert r.case_label == "INVERTED"
    assert r.entry_price is None
    assert r.entry_range is None
    assert r.price_gate_passed is False


def test_inverted_above_bull():
    r = compute_entry_price(120, 90, 130, "quality_compounder")
    assert r.case_label == "INVERTED"
    assert r.entry_price is None
    assert r.entry_range is None


def test_degenerate_crossed_scenarios():
    r = compute_entry_price(90, 120, 100, "deep_value")  # bull <= bear
    assert r.case_label == "DEGENERATE"
    assert r.entry_price is None


def test_degenerate_missing_input():
    r = compute_entry_price(120, None, 100, "deep_value")
    assert r.case_label == "DEGENERATE"


def test_degenerate_nonpositive():
    r = compute_entry_price(120, 90, 0, "deep_value")
    assert r.case_label == "DEGENERATE"


def test_unknown_archetype_no_gate():
    r = compute_entry_price(120, 90, 95, "mystery")
    assert r.archetype_min_rr is None
    assert r.price_gate_passed is None   # cannot gate without a min RR


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
