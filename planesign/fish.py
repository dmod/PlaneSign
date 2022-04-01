#!/usr/bin/python3
# -*- coding: utf-8 -*-

import PIL
import random
from PIL import Image, ImageDraw
import shared_config
import __main__


tankxmin = -100
tankxmax = 227
#tankxmin = 0
#tankxmax = 127
tankymin = 0
tankymax = 31
tankzmin = 0
tankzmax = 5
tankheight = 32

waterlayer = Image.new('RGBA', (128, 32), (25, 140, 200, 10))


tanklayout = current_state = [[0 for j in range(32)] for i in range(128)]

def randomloc():
    return (random.randint(tankxmin,tankxmax),random.randint(tankymin,tankymax),random.randint(tankzmin,tankzmax))

@__main__.planesign_mode_handler(14)
def aquarium(sign):
    sign.canvas.Clear()

    tank = Tank(sign)

    clown = Fish(tank, "Clownfish", 2, 0.01)
    hippo = Fish(tank, "Hippotang", 2, 0.01)
    queentrigger = Fish(tank, "Queentrigger", 1, 0.005)
    grouper = Fish(tank, "Coralgrouper", 1, 0.005)
    anthias = Fish(tank, "Anthias", 2, 0.02)
    puffer = Fish(tank, "Pufferfish", 1.5, 0.005)
    regal = Fish(tank, "Regalangel", 1, 0.005)
    bicolor = Fish(tank, "Bicolorpseudochromis", 3, 0.01)
    flame = Fish(tank, "Flameangel", 1.5, 0.01)
    cardinal = Fish(tank, "Cardinal", 1.5, 0.01)
    copper = Fish(tank, "Copperbanded", 1.5, 0.01)
    wrasse = Fish(tank, "Wrasse", 3, 0.01)

    while shared_config.shared_mode.value == 14:
        tank.swim()
        tank.draw()
        sign.wait_loop(0.1)

class Tank:
    def __init__(self, sign):
        self.background = Image.open(f"{shared_config.icons_dir}/aquarium/Background.png")
        self.fulltank = None
        self.sign = sign
        self.denizens=[]

    def swim(self):
        for fish in self.denizens:
            fish.swim()

    def draw(self):
        
        self.fulltank = self.background.copy()

        for zind in range(tankzmin,tankzmax+1):
            if self.denizens:
                for fish in self.denizens:
                    if fish.z == zind:
                        self.fulltank.paste(fish.sprite, (round(fish.x),round(fish.y)), fish.sprite)
            self.fulltank.paste(waterlayer, (0,0), waterlayer)

        self.sign.canvas.SetImage(self.fulltank.convert('RGB'), 0, 0)
        self.sign.matrix.SwapOnVSync(self.sign.canvas)

class Fish:
    def __init__(self,tank,name,maxspeed,turnprob,dir=random.randint(0,3)):
        self.name = name
        (self.x, self.y, self.z)=randomloc()
        self.maxspeed = maxspeed

        self.vx=random.random()*self.maxspeed
        self.vy=(random.random()*2-1)*self.maxspeed*0.2

        self.turnprob=turnprob #0 to 1

        self.sprite=None
        self.dir=dir #0 front, 1 left, 2 back, 3 right

        self.sprite_right= Image.open(f"{shared_config.icons_dir}/aquarium/{name}_right.png").convert('RGBA').transpose(PIL.Image.FLIP_LEFT_RIGHT)
        self.sprite_left= Image.open(f"{shared_config.icons_dir}/aquarium/{name}_right.png").convert('RGBA')
        self.sprite_front=Image.open(f"{shared_config.icons_dir}/aquarium/{name}_front.png").convert('RGBA')
        self.sprite_back=Image.open(f"{shared_config.icons_dir}/aquarium/{name}_back.png").convert('RGBA')

        self.width, self.height = self.sprite_right.size

        self.set_sprite()
        if tank:
            tank.denizens.append(self)


    def set_sprite(self):
        if self.dir==3:
            self.sprite=self.sprite_right
        elif self.dir==2:
            self.sprite=self.sprite_back
        elif self.dir==1:
            self.sprite=self.sprite_left
        elif self.dir==0:
            self.sprite=self.sprite_front
        else:
            self.sprite=None

    def turn_left(self):
        self.dir=(self.dir+1)%4
        self.set_sprite()

    def turn_right(self):
        self.dir=(self.dir-1)%4
        self.set_sprite()

    def swim(self):
        #0 front, 1 left, 2 back, 3 right

        #change direction
        if ((self.dir == 1 or self.dir == 3) and random.random()<self.turnprob) or ((self.dir == 0 or self.dir == 2) and random.random()<0.5) or (self.dir==0 and self.z==tankzmax) or (self.dir==2 and self.z==tankzmin) or (self.dir==3 and self.x==tankxmin) or (self.dir==1 and self.x==tankxmax-self.width):
            if random.randint(0,1)==0:
                self.turn_left()
            else:
                self.turn_right()
            self.vx += self.maxspeed * 0.5 * random.random()
            if random.randint(0,1)==0:
                self.vy += self.maxspeed * 0.1 * random.random()
            else:
                self.vy -= self.maxspeed * 0.1 * random.random()
        #change forward speed
        elif random.random()<0.3:
            if random.random()<0.5:
                self.vx += self.vx * random.random() * 0.3
            else:
                self.vx -= self.vx * random.random() * 0.3
            if self.vx > self.maxspeed:
                self.vx=self.maxspeed
            elif self.vx < 0:
                self.vx = 0

        #change vertical speed
        if random.random()<0.2:
            if random.randint(0,1)==0:
                self.vy += self.vy * random.random() * 0.2
            else:
                self.vy -= self.vy * random.random() * 0.2
            if self.vy > self.maxspeed*0.5:
                self.vy = self.maxspeed*0.5
            elif self.vy < -self.maxspeed*0.5:
                self.vy = -self.maxspeed*0.5

        if (self.y == tankymin and self.vy<0) or (self.y == tankymax-self.height and self.vy>0):
            self.vy *= -1*random.random()

        if self.dir==0:
            self.z += 1
            self.vx /= 2
            self.vy /= 2
        elif self.dir==2:
            self.z -= 1
            self.vx /= 2
            self.vy /= 2
        elif random.random()<0.001:
            if random.randint(0,1)==0:
                self.z += 1
            else:
                self.z -= 1

            if self.vx > self.maxspeed:
                self.vx = self.maxspeed * 0.2
            if self.vy < -self.maxspeed * 0.2:
                self.vy = -self.maxspeed * 0.2
            elif self.vy > self.maxspeed * 0.2:
                self.vy = self.maxspeed * 0.2

        if self.dir == 3:
            self.x -= self.vx
        else:
            self.x += self.vx

        self.y += self.vy

        if self.x > tankxmax-self.width:
            self.x = tankxmax-self.width
        elif self.x < tankxmin:
            self.x = tankxmin
        
        if self.y > tankymax-self.height:
            self.y = tankymax-self.height
        elif self.y < tankymin:
            self.y = tankymin

        if self.z > tankzmax:
            self.z=tankzmax
        if self.z < tankzmin:
            self.z=tankzmin