#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
import random
import time
import math
import logging
from PIL import Image, ImageEnhance, ImageFilter
import shared_config
import utilities
import __main__
from modes import DisplayMode

class Sprite:
    def __init__(self):
        self.frames = []
        self.maxFrames = 0
        self.currFrame = 0
        self.lastFrame = None
        self.lastDraw = None
        self.lastFrameChange = None
        self.brighten = False
        self.width = 0
        self.height = 0
        self.x0 = 0
        self.y0 = 0
        self.x = 0
        self.y = 0

    def loadframes(self, name):
        while True:
            filename = f"{shared_config.icons_dir}/plants/{name}{self.maxFrames}.png"
            try:
                frame = Image.open(filename).convert("RGBA")
                if self.brighten:
                    converter = ImageEnhance.Color(frame)
                    frame = converter.enhance(1.7)
                    frame = frame.filter(ImageFilter.SHARPEN)
                self.frames.append(frame)
                self.maxFrames += 1
            except FileNotFoundError:
                break
        if self.maxFrames > 0:
            self.width = self.frames[0].size[0]
            self.height = self.frames[0].size[1]
            self.x0 = round(self.width/2)
            self.y0 = self.height-1

    def draw(self, im):
        if self.maxFrames > 0:
            now = time.perf_counter()
            frame = self.frames[self.currFrame].convert("RGBA")
            im.paste(frame, (self.x-self.x0, self.y-self.y0), frame)
            self.lastDraw = now
            if self.currFrame != self.lastFrame:
                self.lastFrameChange = now
                self.lastFrame = self.currFrame

class Plant(Sprite):
    def __init__(self):
        super().__init__()
        self.growthInterval = 1
        self.brighten = True

    def loadframes(self, name):
        super().loadframes(name)
        if self.maxFrames > 0:
            self.currFrame = 1

    def draw(self, im):
        # Change frames if we need to before drawing
        if self.lastFrameChange is not None and (time.perf_counter() >= self.lastFrameChange + self.growthInterval):
            if (self.currFrame < self.maxFrames - 1):
                self.currFrame = self.currFrame + 1

        super().draw(im)

class Critter(Sprite):
    def __init__(self):
        super().__init__()
        self.summonTime = None
        self.lifeTime = 60.0
        self.maxSpeed = 15.0
        self.minSpeed = 2.0
        self.accel = 5.0
        self.speed = 5.0
        self.frameRate = 0.1
        self.lastMove = None
        self.moveInterval = 3
        self.maxMoveInterval = 6
        self.minMoveInterval = 3
        self.realx = None
        self.realy = None
        self.targetX = None
        self.targetY = None
        self.increment = 1
        self.facing = None
        self.boomerang = False
        self.leaveFlag = False
        self.despawnFlag = False

    def summon(self):
        now = time.perf_counter()
        self.summonTime = now
        self.targetX = random.uniform(3.0, 124.0)
        self.targetY = random.uniform(3.0, 28.0)
        self.realx = (random.uniform(-10.0, 0.0) if random.random()<0.5 else random.uniform(128.0, 138.0))
        self.realy = random.uniform(3.0, 28.0)
        self.x = round(self.realx)
        self.y = round(self.realy)

    def leave(self):
        self.leaveFlag = True
        self.targetX = (random.uniform(-10.0, -5.0) if random.random()<0.5 else random.uniform(133.0, 138.0))
        self.targetY = random.uniform(3.0, 28.0)

    def loadframes(self, name):
        super().loadframes(name)
        if self.maxFrames > 0:
            self.currFrame = 0
            self.facing = [-1 for _ in range(self.maxFrames)]

    def move(self):
        # Critter base class has no implementation for moving.
        # Derived classes will implement their own
        return

    def draw(self, im):
        # Change frames if we need to before drawing
        if self.lastFrameChange is not None and (time.perf_counter() >= self.lastFrameChange + self.frameRate):

            if self.boomerang:
                if (self.currFrame >= self.maxFrames - 1):
                    self.increment = -1
                elif (self.currFrame <= 0):
                    self.increment = 1

                self.currFrame += self.increment
            else:
            
                self.currFrame = (self.currFrame + 1) % self.maxFrames

        # Move
        self.move()

        # Change spire direction
        if self.realx > self.targetX:
            facing = -1
        elif self.realx < self.targetX:
            facing = 1
        
        if self.facing[self.currFrame] != facing:
            self.facing[self.currFrame] = facing
            self.frames[self.currFrame] = self.frames[self.currFrame].transpose(Image.FLIP_LEFT_RIGHT)

        super().draw(im)

class FlyingBug(Critter):
    def __init__(self):
        super().__init__()
        self.brighten = True

    def move(self):
        now = time.perf_counter()
        if self.lastDraw is not None:
            dt = now - self.lastDraw
        else:
            dt = 0

        if self.leaveFlag:
            # Leaving
            if math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0 \
               or self.realx < -10.0 or self.realx > 138.0 or self.realy < -10.0 or self.realy > 41.0:
                # Set despawn flag
                self.despawnFlag = True
        else:
            if self.lastMove is None or (now >= self.lastMove + self.moveInterval) or \
            (self.targetX is not None and self.targetY is not None and \
                math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0):
                self.moveInterval = random.uniform(self.minMoveInterval, self.maxMoveInterval)
                self.lastMove = now

                while True:
                    self.targetX = random.uniform(3.0, 124.0)
                    self.targetY = random.uniform(3.0, 28.0)

                    dist = math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY))
                    if (dist > 10.0) and abs(self.realx - self.targetX) > 5.0:
                        break

        dist = math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY))
        direction = math.atan2(self.targetY - self.realy, self.targetX - self.realx)

        dv = self.accel * dt
        if dist <= 10.0:
            dv *= -1

        self.speed = max(self.minSpeed, min(self.speed + dv, self.maxSpeed))
        self.realx += math.cos(direction) * self.speed * dt
        self.realy += math.sin(direction) * self.speed * dt

        self.x = round(self.realx)
        self.y = round(self.realy)

class FireFly(FlyingBug):
    def __init__(self):
        super().__init__()
        super().loadframes("firefly")
        self.lifeTime = random.uniform(60.0, 120.0)
        self.x0 = 2
        self.y0 = 2
        self.summon()

class Bee(FlyingBug):
    def __init__(self):
        super().__init__()
        super().loadframes("bee")
        self.lifeTime = random.uniform(60.0, 120.0)
        self.boomerang = True
        self.x0 = 2
        self.y0 = 2
        self.summon()

class Bird_Base(Critter):
    def __init__(self):
        super().__init__()
        self.brighten = True
        self.lifeTime = random.uniform(45.0, 100.0)
        self.maxSpeed = 25.0
        self.minSpeed = 5.0
        self.accel = 5.0
        self.speed = 10.0
        self.frameRate = 0.2

    def move(self):
        now = time.perf_counter()
        if self.lastDraw is not None:
            dt = now - self.lastDraw
        else:
            dt = 0

        if self.leaveFlag:
            # Leaving
            if math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0 \
               or self.realx < -10.0 or self.realx > 138.0 or self.realy < -10.0 or self.realy > 41.0:
                # Set despawn flag
                self.despawnFlag = True
        else:
            if self.lastMove is None or (now >= self.lastMove + self.moveInterval) or \
            (self.targetX is not None and self.targetY is not None and \
                math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0):
                self.moveInterval = random.uniform(self.minMoveInterval, self.maxMoveInterval)
                self.lastMove = now

                while True:
                    self.targetX = random.uniform(3.0, 124.0)
                    self.targetY = random.uniform(3.0, 28.0)

                    if abs(self.realx - self.targetX) > 15.0:
                        break

        dist = math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY))
        direction = math.atan2(self.targetY - self.realy, self.targetX - self.realx)

        dv = self.accel * dt
        if dist <= 10.0:
            dv *= -1

        self.speed = max(self.minSpeed, min(self.speed + dv, self.maxSpeed))
        self.realx += math.cos(direction) * self.speed * dt
        self.realy += math.sin(direction) * self.speed * dt

        self.x = round(self.realx)
        self.y = round(self.realy)

class Bird(Bird_Base):
    def __init__(self):
        super().__init__()
        super().loadframes("bird_fly")
        self.x0 = 6
        self.y0 = 6
        self.summon()

class Cardinal(Bird_Base):
    def __init__(self):
        super().__init__()
        super().loadframes("cardinal_fly")
        self.x0 = 6
        self.y0 = 6
        self.summon()

class BlueJay(Bird_Base):
    def __init__(self):
        super().__init__()
        super().loadframes("bluejay_fly")
        self.x0 = 6
        self.y0 = 6
        self.summon()

class LadyBug(Critter):
    def __init__(self):
        super().__init__()
        super().loadframes("ladybug_flying")
        self.x0 = 4
        self.y0 = 3
        self.brighten = True
        self.lifeTime = random.uniform(85.0, 120.0)
        self.maxSpeed = 15.0
        self.minSpeed = 5.0
        self.air_accel = 5.0
        self.ground_accel = 1.0
        self.speed = 10.0
        self.frameRate = 0.1
        self.moveInterval = 5
        self.maxMoveInterval = 8
        self.minMoveInterval = 5
        self.summon()

    def move(self):
        now = time.perf_counter()
        if self.lastDraw is not None:
            dt = now - self.lastDraw
        else:
            dt = 0

        if self.leaveFlag:
            # Leaving
            if math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0 \
               or self.realx < -10.0 or self.realx > 138.0 or self.realy < -10.0 or self.realy > 41.0:
                # Set despawn flag
                self.despawnFlag = True
        else:
            if self.lastMove is None or (now >= self.lastMove + self.moveInterval) or \
            (self.targetX is not None and self.targetY is not None and \
                math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY)) < 1.0):
                self.moveInterval = random.uniform(self.minMoveInterval, self.maxMoveInterval)
                self.lastMove = now

                while True:
                    self.targetX = random.uniform(3.0, 124.0)
                    self.targetY = random.uniform(3.0, 28.0)

                    dist = math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY))
                    if (dist > 10.0) and abs(self.realx - self.targetX) > 8.0:
                        break

        dist = math.hypot(abs(self.realx - self.targetX), abs(self.realy - self.targetY))
        direction = math.atan2(self.targetY - self.realy, self.targetX - self.realx)

        dv = self.accel * dt
        if dist <= 10.0:
            dv *= -1

        self.speed = max(self.minSpeed, min(self.speed + dv, self.maxSpeed))
        self.realx += math.cos(direction) * self.speed * dt
        self.realy += math.sin(direction) * self.speed * dt

        self.x = round(self.realx)
        self.y = round(self.realy)

def handle_critters(critters):

    now = time.perf_counter()

    # Handle despawning
    for critter in critters:
        if (critter.despawnFlag):
            critters.remove(critter)
        elif (not critter.leaveFlag):
            if (critter.summonTime is not None and now >= critter.summonTime + critter.lifeTime):
                critter.leave()

    num_critters = len(critters)

    bees = [critter for critter in critters if critter.__class__.__name__ == "Bee"]
    num_bees = len(bees)

    fireflies = [critter for critter in critters if critter.__class__.__name__ == "FireFly"]
    num_fireflies = len(fireflies)

    birds = [critter for critter in critters if critter.__class__.__name__ in ["Bird", "Cardinal", "BlueJay"]]
    num_birds = len(birds)

    ladybugs = [critter for critter in critters if critter.__class__.__name__ == "LadyBug"]
    num_ladybugs = len(ladybugs)

    if handle_critters.lastSummonAttempt is None or now >= handle_critters.lastSummonAttempt + handle_critters.summonAttemptInterval:
        
        handle_critters.lastSummonAttempt = now

        if num_critters < handle_critters.maxCritters:

            # Determine which type of critter to try summoning
            r = random.random()

            if r < 0.25:
                # Bee
                if num_bees < 3 and random.random() < 0.2:
                    critter = Bee()
                    critters.append(critter)
            elif r < 0.5:
                # Firefly
                if num_fireflies < 5  and random.random() < 0.25:
                    critter = FireFly()
                    critters.append(critter)
            elif r < 0.75:
                # Ladybug
                if num_ladybugs < 2 and random.random() < 0.3:
                    critter = LadyBug()
                    critters.append(critter)
            else:
                # Bird
                if num_birds < 1 and random.random() < 0.1:
                    b = random.randint(0,2)
                    if b == 0:
                        critter = Bird()
                    elif b == 1:
                        critter = Cardinal()
                    else:
                        critter = BlueJay()
                    critters.append(critter)


@__main__.planesign_mode_handler(DisplayMode.PLANTS)
def plantmode(sign):
    sign.canvas.Clear()

    handle_critters.lastSummonAttempt = None
    handle_critters.summonAttemptInterval = 30
    handle_critters.maxCritters = 5

    background = Image.open(f"{shared_config.icons_dir}/plants/Background.png").convert('RGB')

    # Format is: (Plant name, x0, y0, growthInterval (mins), 0 <= availability weight <= 1)
    plantlist = [("Alocasia",        8,   25,    1.5+random.random(),    1.0),
                ("Amaryllis",        8,   27,    1+random.random(),      1.0),
                ("Anthurium",        6,   21,    1+random.random(),      1.0),
                ("Begonia",          10,  22,    1.5+random.random(),    0.9),
                ("Bonsai",           8,   17,    9+random.random(),      0.1),
                ("Bromeliad",        11,  22,    2+random.random(),      1.0),
                ("Cactus",           4,   13,    5+random.random(),      1.0),
                ("Cattleya",         6,   23,    2+random.random(),      1.0),
                ("CrownOfThorns",    8,   22,    3+random.random(),      1.0),
                ("Codiaeum",         9,   27,    1.5+random.random(),    1.0),
                ("Daisy",            4,   19,    1.5+random.random(),    1.0),
                ("Dendrobium",       8,   25,    1.5+random.random(),    1.0),
                ("Dracaena",         8,   23,    2.5+random.random(),    1.0),
                ("EnglishIvy",       15,  18,    1+random.random(),      1.0),
                ("Fern",             6,   13,    1+random.random(),      1.0),
                ("Hibiscus",         10,  26,    1+random.random(),      1.0),
                ("Kalanchoe",        6,   14,    1+random.random(),      1.0),
                ("LadySlipper",      6,   25,    2+random.random(),      1.0),
                ("Lavender",         6,   25,    1+random.random(),      1.0),
                ("Masdevallia",      8,   29,    1.5+random.random(),    1.0),
                ("Orchid",           8,   22,    2+random.random(),      1.0),
                ("PeaceLily",        7,   22,    1+random.random(),      1.0),
                ("Phalanopsis_Pink", 11,  26,    2+random.random(),      1.0),
                ("Phalanopsis_Purple", 6, 25,    2+random.random(),      1.0),
                ("Philodendron",     13,  23,    2+random.random(),      0.9),
                ("Pitcherplant",     13,  20,    3+random.random(),      0.7),
                ("PonytailPalm",     8,   24,    2+random.random(),      0.9),
                ("Pothos",           8,   18,    1+random.random(),      1.0),
                ("Prayerplant",      13,  23,    2+random.random(),      0.6),
                ("Rafflesia",        13,  23,    10*(1+random.random()), 0.05),
                ("Rubberplant",      7,   26,    2+random.random(),      0.8),
                ("SagoPalm",         11,  24,    1.5+random.random(),    0.9),
                ("SpiderPlant",      9,   16,    1+random.random(),      1.0),
                ("Succulent",        4,   9,     3+random.random(),      1.0),
                ("Vanda",            10,  25,    1.5+random.random(),    1.0),
                ("Violet",           5,   15,    1+random.random(),      1.0),
                ("XmasCactus",       12,  14,    1+random.random(),      1.0)]

    edge = 2
    extent = edge-1
    miny = 23
    maxy = 28
    attempt = 0
    max_attempts = 5
    min_plants = 6

    while True:

        attempt += 1

        # Keep plants based on their availability
        curatedlist = [p for p in plantlist if random.random() < p[4]]

        plants = []

        # Select random plants to fill the table
        while True:
            if (len(curatedlist) == 0):
                break

            index = random.randint(0, len(curatedlist)-1)

            (name, x0, y0, growthInterval, _) = curatedlist[index]
            del curatedlist[index]

            plant = Plant()
            plant.loadframes(name)
            plant.x0 = x0
            plant.y0 = y0
            plant.growthInterval = growthInterval * 60
            center = round(plant.width/2 + extent - 0.5)
            left = center
            right = center + 1
            plant.x = random.randint(left, right)
            ywiggle = max(0, 32 - plant.height - 1)
            bot = maxy
            top = max(miny, bot - ywiggle)
            plant.y = random.randint(top, bot)
            test_extent = plant.x + round(plant.width/2 - 0.5)
            
            if (test_extent <= 127 - edge):
                # Plant fits on the table
                plants.append(plant)
                extent = test_extent

        if (len(plants) >= min_plants or attempt >= max_attempts):
            # Try and get more than 5 plants on the table at once
            break

    plants = sorted(plants, key=lambda p: p.y)

    # Summoned critters list
    critters = []

    while shared_config.shared_mode.value == DisplayMode.PLANTS.value:

        bg = background.copy()

        for plant in plants:
            plant.draw(bg)

        handle_critters(critters)

        for critter in critters:
            critter.draw(bg)

        sign.canvas.SetImage(bg.convert('RGB'), 0, 0)
        
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        breakout = sign.wait_loop(0.01)
        if breakout:
            break
