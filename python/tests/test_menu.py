import unittest
from PiFinder.menu import MenuScroller


class TestStringMethods(unittest.TestCase):
    catalogs = [
        "NGC",
        "IC",
        "M",
        "C",
        "Col",
        "H",
        "Ta2",
        "Str",
        "SaA",
        "SaM",
        "SaR",
        "EGC",
    ]

    def setUp(self):
        self.menu = MenuScroller(self.catalogs)

    def test_initial_state(self):
        window = ["NGC", "IC", "M", "C", "Col", "H", "Ta2", "Str", "SaA", "SaM"]
        self.assertEqual(self.menu.get_options_window(), window)

    def test_down(self):
        window = ["NGC", "IC", "M", "C", "Col", "H", "Ta2", "Str", "SaA", "SaM"]
        print(self.menu)
        self.assertEqual(self.menu.get_options_window(), window)
        self.menu.down()  # IC
        print(self.menu)
        self.assertEqual(self.menu.get_options_window()[0], "IC")
        self.assertEqual(self.menu.get_selected(), window[1])
        self.menu.down()  # M
        print(self.menu)
        self.menu.down()  # C
        print(self.menu)
        self.menu.down()  # Col
        print(self.menu)
        self.menu.down()  # H
        print(self.menu)
        self.menu.down()  # Ta2
        print(self.menu)
        self.menu.down()  # Str
        print(self.menu)
        self.menu.down()  # SaA
        print(self.menu)
        self.menu.down()  # SaM
        print(self.menu)
        self.menu.down()  # Str
        print(self.menu)
        self.menu.down()  # Str
        print(self.menu)
        self.assertEqual(self.menu.get_selected(), window[3])
        window = ["NGC", "IC", "M", "C", "Col", "H", "Ta2", "Str", "SaA", "SaM"]
        # self.assertEqual(self.menu.get_options_window(), window)
        # window = [ "NGC", "IC", "M", "C", "Col", "H", "Ta2", "Str", "SaA", "SaM"]
        # self.assertEqual(self.menu.get_options_window(), window)

    def test_split(self):
        s = "hello world"
        self.assertEqual(s.split(), ["hello", "world"])
        # check that s.split fails when the separator is not a string
        with self.assertRaises(TypeError):
            s.split(2)


if __name__ == "__main__":
    unittest.main()
