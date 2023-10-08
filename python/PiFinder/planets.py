from PiFinder.calc_utils import sf_utils as sf


class Planet:
    def __init__(self):
        earth = sf.eph["earth"]
        mars = sf.eph["mars"]
        sf.set_location(51, 3.7, 50)
        print(mars.at(sf.ts.now()).observe(earth).apparent())
