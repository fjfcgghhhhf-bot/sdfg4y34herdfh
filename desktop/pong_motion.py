"""Timestamped Pong playback independent of HTTP arrival cadence."""
from collections import deque
import math


class PongTimeline:
    def __init__(self):
        self.samples = deque(maxlen=240)
        self.cursor = None
        self.last_draw = None
        self.last_arrival = None
        self.interval = .15
        self.delay = .22

    def receive(self, samples, now):
        fresh = [tuple(s) for s in samples if not self.samples or s[0] > self.samples[-1][0]]
        if not fresh:
            return  # A general status poll can repeat an older frame.
        self.samples.extend(fresh)
        if self.last_arrival is not None:
            gap = max(.01, min(.6, now-self.last_arrival))
            self.interval += (gap-self.interval)*.2
            desired = min(.45, max(.12, self.interval*1.5, gap*1.2))
            self.delay += (desired-self.delay)*(.6 if desired>self.delay else .1)
        self.last_arrival = now
        if self.cursor is None:
            self.cursor = self.samples[-1][0]-self.delay
            self.last_draw = now

    def draw(self, now):
        if not self.samples:
            return None
        dt = min(.1, max(0, now-self.last_draw))
        self.last_draw = now
        newest = self.samples[-1][0]
        # Gradual clock correction: never reset the ball to an arriving packet.
        ahead = newest-self.cursor
        speed = min(1.18, max(.82, 1+(ahead-self.delay)*1.5))
        self.cursor = min(newest, self.cursor+dt*speed)
        while len(self.samples)>2 and self.samples[1][0]<=self.cursor:
            self.samples.popleft()
        a, b = self.samples[0], self.samples[min(1, len(self.samples)-1)]
        fraction = max(0, min(1, (self.cursor-a[0])/max(1e-9, b[0]-a[0])))
        return tuple(a[i]+(b[i]-a[i])*fraction for i in range(1, 5))


def blend_correction(error, dt):
    """Frame-rate independent convergence, without a position snap."""
    return error*(1-math.exp(-8*dt))
