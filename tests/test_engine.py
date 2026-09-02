import unittest

from app import engine


def block(
    duty=0.35,
    excise=0.2,
    excise_fixed=None,
    vat=0.16,
    rdl=0.02,
    idf=0.025,
    initial=1.25,
    divisors=None,
):
    return {
        "duty_rate": duty,
        "excise_rate": excise,
        "excise_fixed": excise_fixed,
        "vat_rate": vat,
        "rdl_rate": rdl,
        "idf_rate": idf,
        "initial_divisor": initial,
        "backout_divisors": divisors or [1.35, 1.2, 1.16],
    }


DIRECT_DEP = [
    {"low": 1, "high": 2, "rate": 0.2},
    {"low": 2, "high": 3, "rate": 0.3},
    {"low": 3, "high": 4, "rate": 0.4},
    {"low": 4, "high": 5, "rate": 0.5},
    {"low": 5, "high": 6, "rate": 0.55},
    {"low": 6, "high": 7, "rate": 0.6},
    {"low": 7, "high": 8, "rate": 0.65},
]

REGISTERED_DEP = [
    {"low": age, "high": age, "rate": rate}
    for age, rate in (
        (1, 0.2), (2, 0.35), (3, 0.5), (4, 0.6), (5, 0.7),
        (6, 0.75), (7, 0.8), (8, 0.83), (9, 0.86), (10, 0.89),
        (11, 0.9), (12, 0.91), (13, 0.92), (14, 0.93), (15, 0.94),
    )
] + [{"low": 999, "high": None, "rate": 0.95}]


class ClassificationTest(unittest.TestCase):
    def test_regular_routes(self):
        self.assertEqual(engine.classify_block("passenger", "petrol", 1499)[0], "mv_small")
        self.assertEqual(engine.classify_block("passenger", "petrol", 1500)[0], "mv_small")
        self.assertEqual(engine.classify_block("passenger", "petrol", 2000)[0], "mv_large")
        self.assertEqual(engine.classify_block("pickup", "diesel", 3000)[0], "mv_large")
        self.assertEqual(engine.classify_block("van_minibus", "diesel", 1200)[0], "mv_small")

    def test_high_cc_passenger_routes(self):
        self.assertEqual(engine.classify_block("passenger", "petrol", 3001)[0], "mv_high_cc")
        self.assertEqual(engine.classify_block("passenger", "diesel", 2600)[0], "mv_high_cc")
        self.assertEqual(engine.classify_block("passenger", "diesel", 2400)[0], "mv_large")

    def test_special_routes(self):
        self.assertEqual(engine.classify_block("ambulance", "", None)[0], "ambulance")
        self.assertEqual(engine.classify_block("school_bus", "", None)[0], "school_bus")
        self.assertEqual(engine.classify_block("motorcycle", "", None)[0], "motorcycle")
        self.assertEqual(engine.classify_block("machinery", "", None)[0], "heavy_machinery")

    def test_electric(self):
        self.assertEqual(engine.classify_block("passenger", "electric", None)[0], "electric")
        with self.assertRaises(ValueError):
            engine.classify_block("pickup", "electric", None)


class DepreciationTest(unittest.TestCase):
    def test_direct(self):
        self.assertEqual(engine.depreciation_rate(DIRECT_DEP, "direct", 1), 0.0)
        self.assertEqual(engine.depreciation_rate(DIRECT_DEP, "direct", 2), 0.2)
        self.assertEqual(engine.depreciation_rate(DIRECT_DEP, "direct", 8), 0.65)
        self.assertIsNone(engine.depreciation_rate(DIRECT_DEP, "direct", 9))

    def test_registered(self):
        self.assertEqual(engine.depreciation_rate(REGISTERED_DEP, "registered", 1), 0.2)
        self.assertEqual(engine.depreciation_rate(REGISTERED_DEP, "registered", 8), 0.83)
        self.assertEqual(engine.depreciation_rate(REGISTERED_DEP, "registered", 16), 0.95)
        self.assertEqual(engine.depreciation_rate(REGISTERED_DEP, "registered", 0), 0.0)


class CalculateTest(unittest.TestCase):
    """Golden values taken directly from the July 2025 TEMPLATE sheet (CRSP = 1000)."""

    def test_small_car_direct(self):
        result = engine.calculate(block(), "direct", 1000, 0)
        self.assertAlmostEqual(result["customs_value"], 425.71306939123036, places=2)
        self.assertAlmostEqual(result["import_duty"], 148.99957428693062, places=2)
        self.assertAlmostEqual(result["excise_duty"], 114.9425287356322, places=2)
        self.assertAlmostEqual(result["vat"], 110.3448275862069, places=2)
        self.assertAlmostEqual(result["rdl"], 8.514261387824607, places=2)
        self.assertAlmostEqual(result["idf"], 10.64282673478076, places=2)
        self.assertAlmostEqual(result["grand_total"], 393.44401873137514, places=2)

    def test_small_car_registered_no_rdl_idf(self):
        result = engine.calculate(block(), "registered", 1000, 0)
        self.assertEqual(result["rdl"], 0)
        self.assertEqual(result["idf"], 0)
        self.assertAlmostEqual(result["grand_total"], 374.28693060876975, places=2)

    def test_motorcycle_with_fixed_excise(self):
        mc = block(
            duty=0.25,
            excise=None,
            excise_fixed=12953.0,
            divisors=[1.25, 1.16],
        )
        result = engine.calculate(mc, "direct", 1000, 0)
        self.assertAlmostEqual(result["customs_value"], 551.7241379310345, places=2)
        self.assertAlmostEqual(result["import_duty"], 137.93103448275863, places=2)
        self.assertAlmostEqual(result["excise_duty"], 12953.0, places=2)
        self.assertAlmostEqual(result["vat"], 2182.824827586207, places=2)
        self.assertAlmostEqual(result["grand_total"], 15298.583448275864, places=2)


if __name__ == "__main__":
    unittest.main()
