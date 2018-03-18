import sys
import logging
import traceback

from copy import deepcopy
from clock import Clock, ClockException
from airport import AirportFactory
from scenario import ScenarioFactory
from routing_expert import RoutingExpert
from analyst import Analyst
from utils import get_seconds_after, get_seconds_before
from uncertainty import Uncertainty
from config import Config
import importlib
import numpy as np


class Simulation:

    def __init__(self):

        p = Config.params

        # Setups the logger
        self.logger = logging.getLogger(__name__)

        # Setups the clock
        self.clock = Clock()

        # Sets up the airport
        airport_code = p["airport"]
        self.airport = AirportFactory.create(self, airport_code)

        # Sets up the scenario
        self.scenario = ScenarioFactory.create(self, airport_code,
                                               self.airport.surface)

        # Sets up the routing expert monitoring the airport surface
        self.routing_expert = RoutingExpert(self.airport.surface.links,
                                            self.airport.surface.nodes,
                                            p["simulation"]["cache"])

        # Sets up the uncertainty module
        self.uncertainty = (Uncertainty() if p["uncertainty"]["enabled"]
                            else (None))

        # Loads the requested scheduler
        scheduler_name = p["scheduler"]["name"]
        scheduler_module = \
                importlib.import_module("scheduler." + scheduler_name)
        self.scheduler = scheduler_module.Scheduler()

        # Sets up the analyst
        if p["analyst"]["enabled"]:
            self.analyst = Analyst(self.clock.sim_time)

        # Sets up a delegate of this simulation
        self.delegate = SimulationDelegate(self)

        # Initializes the previous schedule time
        self.last_schedule_time = None
        self.print_stats()

    def tick(self):

        self.logger.debug("\nCurrent Time: %s" % self.now)

        try:

            self.add_aircrafts()
            if self.is_time_to_reschedule():
                self.logger.info("Time to reschedule")
                self.reschedule()
                self.last_schedule_time = self.now
                self.logger.info("Last schedule time is updated to %s" %
                                 self.last_schedule_time)

            # Injects uncertainties
            if self.uncertainty:
                self.uncertainty.inject(self)

            # Tick
            self.airport.tick()
            self.remove_aircrafts()
            self.clock.tick()

            # Observe
            if Config.params["analyst"]["enabled"]:
                self.analyst.observe_on_tick(self.delegate)

        except ClockException as e:
            # Finishes
            if Config.params["analyst"]["enabled"]:
                self.analyst.print_summary(self)
            raise e
        except Exception as e:
            self.logger.error(traceback.format_exc())
            raise e

    def quiet_tick(self):
        """
        Turn off the logger, reschedule, and analyst.
        """
        self.add_aircrafts()
        self.remove_aircrafts()

        self.airport.tick()
        try:
            self.clock.tick()
        except ClockException as e:
            raise e

    def is_time_to_reschedule(self):
        reschedule_cycle = Config.params["simulation"]["reschedule_cycle"]
        last_time = self.last_schedule_time
        next_time = (get_seconds_after(last_time, reschedule_cycle)
                     if last_time is not None else None)
        return last_time is None or next_time <= self.now

    def reschedule(self):
        schedule = self.scheduler.schedule(self.delegate)
        self.airport.apply_schedule(schedule)
        # from IPython.core.debugger import Tracer; Tracer()()

    def add_aircrafts(self):

        # NOTE: we will only focus on departures now
        next_tick_time = get_seconds_after(self.now, self.clock.sim_time)

        # For all departure flights
        for flight in self.scenario.departures:
            # If it the scheduled appear time is between now and next tick time
            if self.now <= flight.appear_time and \
               flight.appear_time < next_tick_time:

                self.logger.info("Adds %s into the airport" % flight)

                # Adds the flight to the airport
                flight.aircraft.set_location(flight.from_gate)
                self.airport.add_aircraft(flight.aircraft)

    def remove_aircrafts(self):
        """
        Removes departure aircrafts if they've moved to the runway.
        """
        # TODO: removal for arrival aircrafts

        to_remove_aircrafts = []

        for aircraft in self.airport.aircrafts:
            flight = self.scenario.get_flight(aircraft)
            # Deletion shouldn't be done in the fly
            if aircraft.location.is_close_to(flight.runway.start):
                to_remove_aircrafts.append(aircraft)

        for aircraft in to_remove_aircrafts:
            self.logger.info("Removes %s from the airport" % aircraft)
            self.airport.remove_aircraft(aircraft)

    @property
    def now(self):
        return self.clock.now

    def print_stats(self):
        self.scenario.print_stats()
        self.airport.print_stats()

    def __getstate__(self):
        d = dict(self.__dict__)
        del d["logger"]
        return d

    def __setstate__(self, d):
        self.__dict__.update(d)

    def set_quiet(self, logger):
        self.logger = logger
        self.airport.set_quiet(logger)
        self.scenario.set_quiet(logger)
        self.routing_expert.set_quiet(logger)


class SimulationDelegate:
    """
    SimulationDelegate is used for scheduler to access simulation state without
    breaking on-going things or creating deadlocks.
    """

    def __init__(self, simulation):
        self.simulation = simulation

    @property
    def now(self):
        return self.simulation.now

    @property
    def airport(self):
        # TODO: should make it immutable before returning the airport state
        return self.simulation.airport

    @property
    def scenario(self):
        return self.simulation.scenario

    @property
    def routing_expert(self):
        return self.simulation.routing_expert

    def predict_state_after(self, scheule, time_from_now, uncertainty=None):
        """
        Returns the simulation state after `time_from_now` seconds.
        """

        # Gets a snapshot of current simulation state
        simulation_copy = deepcopy(self.simulation)

        # Replace the uncertainty module by the given one
        simulation_copy.uncertainty = uncertainty

        # Sets the simulation to quiet mode
        simulation_copy.set_quiet(logging.getLogger("QUIET_MODE"))

        # Applies the schedule
        simulation_copy.airport.apply_schedule(scheule)

        # Starts to simulate the future state
        for i in range(int(time_from_now / simulation_copy.clock.sim_time)):
            simulation_copy.quiet_tick()

        return simulation_copy
