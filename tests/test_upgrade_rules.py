"""Вероятности и конечный угол проверяются независимо от отрисовки Qt."""
from collections import Counter
import unittest

from upgrade_rules import roll_upgrade


class Draws:
    """Явные броски позволяют точно проверить границы без статистической погрешности."""
    def __init__(self, appearance, hit=99, ordinary=0, angle=500_000):
        self.expected = [(100, appearance)]
        if appearance < 30:
            self.expected.append((100, hit))
        if appearance >= 30 or hit >= 30:
            self.expected.append((100, ordinary))
        self.expected.append((1_000_000, angle))

    def __call__(self, bound):
        expected_bound, value = self.expected.pop(0)
        assert bound == expected_bound, (bound, expected_bound)
        assert 0 <= value < bound
        return value


def distance_from_bottom(angle):
    return abs((angle - 90 + 180) % 360 - 180)


class UpgradeRulesTests(unittest.TestCase):
    def test_appearance_and_conditional_hit_are_exactly_thirty_percent(self):
        counts = Counter()
        for appearance in range(100):
            for hit in range(100):
                draws = Draws(appearance, hit)
                result = roll_upgrade(50, draws)
                counts['appeared'] += result['special']
                counts['immune'] += result['result'] == 'immune'
                self.assertEqual(draws.expected, [])
        self.assertEqual(counts['appeared'], 3000)
        self.assertEqual(counts['immune'], 900)  # 30% × 30% = 9% всех вращений.

    def test_normal_probability_has_exact_selected_threshold(self):
        for chance in (0, 1, 25, 50, 75, 99, 100):
            for appearance in (0, 99):
                outcomes = Counter(roll_upgrade(chance, Draws(appearance, 99, ordinary))['result']
                                   for ordinary in range(100))
                self.assertEqual(outcomes['win'], chance)
                self.assertEqual(outcomes['loss'], 100 - chance)
                self.assertEqual(outcomes['immune'], 0)

    def test_every_endpoint_matches_visible_sector_even_at_extreme_chances(self):
        for chance in (0, 1, 5, 25, 50, 75, 99, 100):
            for appearance, hit, ordinary in ((0, 0, 0), (0, 99, 0), (0, 99, 99), (99, 99, 0), (99, 99, 99)):
                for angle_draw in (0, 1, 250_000, 499_999, 500_000, 750_000, 999_999):
                    with self.subTest(chance=chance, appearance=appearance, hit=hit, ordinary=ordinary, angle=angle_draw):
                        data = roll_upgrade(chance, Draws(appearance, hit, ordinary, angle_draw))
                        self.assertEqual(data['chance'], chance)
                        self.assertGreaterEqual(data['angle'], 0)
                        self.assertLess(data['angle'], 360)
                        delta = distance_from_bottom(data['angle'])
                        width = data['target_half_width']
                        self.assertGreater(width, 0)
                        self.assertLessEqual(width, 8)
                        if data['result'] == 'immune':
                            self.assertTrue(data['special'])
                            self.assertLess(delta, width)
                        else:
                            if data['special']:
                                self.assertGreater(delta, width)
                            if data['result'] == 'win':
                                self.assertLess(delta, 1.8 * chance)
                            else:
                                self.assertGreater(delta, 1.8 * chance)

    def test_zero_and_hundred_do_not_remove_the_independent_bonus(self):
        for chance in (0, 100):
            self.assertEqual(roll_upgrade(chance, Draws(0, 0))['result'], 'immune')

    def test_invalid_chance_rejected_before_any_random_draw(self):
        def unexpected(_):
            self.fail('Неверный шанс не должен запускать розыгрыш.')
        for chance in (True, False, -1, 101, 50.0, float('nan'), float('inf'), '50', None, [], {}):
            with self.subTest(chance=chance):
                with self.assertRaises(ValueError):
                    roll_upgrade(chance, unexpected)


if __name__ == '__main__':
    unittest.main()
