import os
import logging
import itertools

from surface import SurfaceFactory
from config import Config
from conflict import Conflict
from aircraft import State
from node import get_middle_node


class Airport:
    """
    Airport contains the surface and all the aircrafts currently moving or
    stopped in this airport.
    """

    def __init__(self, simulation, code, surface):

        # Setups the logger
        self.logger = logging.getLogger(__name__)

        # Runtime data
        self.aircrafts = []

        # Pointer to the simulation
        self.simulation = simulation

        # Static data
        self.code = code
        self.surface = surface

    def apply_schedule(self, schedule):
        for r in schedule.requests:
            if r.aircraft not in self.aircrafts:
                raise Exception("%s not found in the airport" % r.aircraft)
            r.aircraft.set_itinerary(r.itinerary)

    def add_aircraft(self, aircraft):
        self.aircrafts.append(aircraft)

    def remove_aircraft(self, aircraft):
        self.aircrafts.remove(aircraft)

    @property
    def conflicts_at_node(self):

        occupied_by = {}
        for aircraft in self.aircrafts:
            if aircraft.state == State.moving:
                continue
            location = aircraft.location
            entry = occupied_by.get(location, [])
            entry.append(aircraft)
            occupied_by[location] = entry

        now = self.simulation.now
        result = []
        for location in occupied_by:
            aircrafts = occupied_by[location]
            if len(aircrafts) <= 1:
                continue
            result.append(Conflict(location, aircrafts, now))
        return result

    @property
    def conflicts(self):

        separation = Config.params["simulation"]["separation"]

        cs = []

        aircraft_pairs = list(itertools.combinations(self.aircrafts, 2))
        for ap in aircraft_pairs:
            d = ap[0].location.get_distance_to(ap[1].location)
            if d > separation:
                continue
            middle_node = get_middle_node(ap[0].location, ap[1].location)
            cs.append(Conflict(middle_node, ap, self.simulation.now))

        return cs

    def tick(self):
        for aircraft in self.aircrafts:
            aircraft.pilot.tick()

    def print_stats(self):
        self.surface.print_stats()

    def __getstate__(self):
        d = dict(self.__dict__)
        del d["logger"]
        return d

    def __setstate__(self, d):
        self.__dict__.update(d)

    def set_quiet(self, logger):
        self.logger = logger
        self.surface.set_quiet(logger)
        for aircraft in self.aircrafts:
            aircraft.set_quiet(logger)


class AirportFactory:

    @classmethod
    def create(self, simulation, code):

        dir_path = Config.DATA_ROOT_DIR_PATH % code

        # Checks if the folder exists
        if not os.path.exists(dir_path):
            raise Exception("Surface data is missing")

        surface = SurfaceFactory.create(dir_path)
        return Airport(simulation, code, surface)
