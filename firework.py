#!/usr/bin/python3
# -*- coding: utf-8 -*-

from random import randint, random, randrange
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
import math
import time
from utilities import *
import numpy as np

TRAIL_PARTICLE = 0
RING_PARTICLE = 1
WILLOW_PARTICLE = 2
TRACER_PARTICLE = 3
CRACKLER_PARTICLE = 4


RING_FW = 0
WILLOW_FW = 1
TRACER_FW = 2
CRACKLER_FW = 3

class Particle:
    def __init__(self,fwlist,ptype,x,y,color,lifetime,speed=0,angle=0):
        self.x0=x
        self.y0=y
        self.x=x
        self.y=y
        self.list=fwlist
        self.spawn_time=time.perf_counter()
        self.lifetime=lifetime
        self.r0,self.g0,self.b0=color
        self.r=self.r0
        self.g=self.g0
        self.b=self.b0
        self.speed=speed
        self.angle=angle
        self.ptype=ptype
        self.list.append(self)

    def update(self):
        time_alive = time.perf_counter()-self.spawn_time

        if self.ptype==TRAIL_PARTICLE:
            tempr = int(round(self.r0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempr < 0:
                self.r=0
            elif tempr > 255:
                self.r=255
            else:
                self.r=tempr
            tempg = int(round(self.g0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempg < 0:
                self.g=0
            elif tempg > 255:
                self.g=255
            else:
                self.g=tempg
            tempb = int(round(self.b0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempb < 0:
                self.b=0
            elif tempb > 255:
                self.b=255
            else:
                self.b=tempb

        elif self.ptype==TRACER_PARTICLE:
            tempr = int(round(self.r0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempr < 0:
                self.r=0
            elif tempr > 255:
                self.r=255
            else:
                self.r=tempr
            tempg = int(round(self.g0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempg < 0:
                self.g=0
            elif tempg > 255:
                self.g=255
            else:
                self.g=tempg
            tempb = int(round(self.b0*(math.sin(self.speed*time_alive)**2)*(math.tanh(-time_alive)+1)))
            if tempb < 0:
                self.b=0
            elif tempb > 255:
                self.b=255
            else:
                self.b=tempb

        elif self.ptype == RING_PARTICLE:
            self.x = self.x0+math.cos(self.angle)*self.speed*time_alive
            self.y = self.y0+math.sin(self.angle)*self.speed*time_alive
            tempr = int(round(self.r0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempr < 0:
                self.r=0
            elif tempr > 255:
                self.r=255
            else:
                self.r=tempr
            tempg = int(round(self.g0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempg < 0:
                self.g=0
            elif tempg > 255:
                self.g=255
            else:
                self.g=tempg
            tempb = int(round(self.b0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempb < 0:
                self.b=0
            elif tempb > 255:
                self.b=255
            else:
                self.b=tempb

        elif self.ptype == WILLOW_PARTICLE:
            if random.random()<0.1:
                Particle(self.list,TRACER_PARTICLE,self.x,self.y,(self.r,self.g,self.b),3+random.random()*2,3+random.random()*2)
            self.x = self.x0+math.cos(self.angle)*self.speed*(time_alive**0.5)
            self.y = self.y0+math.sin(self.angle)*self.speed*time_alive + 1*(time_alive**2)
            tempr = int(round(self.r0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempr < 0:
                self.r=0
            elif tempr > 255:
                self.r=255
            else:
                self.r=tempr
            tempg = int(round(self.g0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempg < 0:
                self.g=0
            elif tempg > 255:
                self.g=255
            else:
                self.g=tempg
            tempb = int(round(self.b0*(math.tanh(-time_alive+self.lifetime+0.05)+1)/2))
            if tempb < 0:
                self.b=0
            elif tempb > 255:
                self.b=255
            else:
                self.b=tempb

        elif self.ptype == CRACKLER_PARTICLE:

            if time_alive<self.lifetime-0.4:
                self.r=0
                self.g=0
                self.b=0
            else:
                self.r=self.r0
                self.g=self.g0
                self.b=self.b0


        if time_alive > self.lifetime or self.x<0 or self.x>127 or self.y<0 or self.y>31:
            self.r=0
            self.g=0
            self.b=0
            self.list.remove(self)
            return
        


class Firework:
    def __init__(self,sign,ftype):
        self.sign = sign
        self.launch_time = time.perf_counter()
        self.fuse = 1.5+random.random()*3
        self.speed = 4+random.random()*2 #pixels/second
        self.x = randint(5,122)
        self.y0 = 31
        self.y = self.y0
        self.ftype = ftype
        self.exploded=0
        self.explosion_particles=[]
        self.trail_particles=[]

    def draw(self):
        if self.exploded==1 and len(self.explosion_particles)==0 and len(self.trail_particles)==0:
            self.exploded=2
        elif time.perf_counter() > self.launch_time + self.fuse and self.exploded==0:
            self.explode()
        elif self.exploded==0:
            self.y = self.y0 - self.speed*(time.perf_counter()-self.launch_time)
            if random.random() < 0.6:
                Particle(self.trail_particles,TRAIL_PARTICLE,self.x,self.y,(randint(230,255),randint(150,230),0),0.5+random.random()*2,3+random.random()*7)
        
        for p in self.trail_particles:
            p.update()
        for p in self.trail_particles:
            self.sign.canvas.SetPixel(round(p.x), round(p.y), p.r, p.g, p.b)
        for p in self.explosion_particles:
            p.update()
        for p in self.explosion_particles:
            if p.r+p.g+p.b>0:
                self.sign.canvas.SetPixel(round(p.x), round(p.y), p.r, p.g, p.b)

    def explode(self):
        self.exploded=1
        n=randint(6,14)
        offset=random.random()*360
        lifetime = 1+random.random()
        speed = 5.5
        if self.ftype == RING_FW or self.ftype == WILLOW_FW:
            color = hsv_2_rgb(random.random(), 0.6+random.random()*0.4, 1)
            for i in range(n):
                angle=((360*i/n+offset)%360)*DEG_2_RAD
                
                if self.ftype == RING_FW:
                    Particle(self.explosion_particles,RING_PARTICLE,self.x,self.y,color,lifetime,speed,angle)
                elif self.ftype == WILLOW_FW:
                    Particle(self.explosion_particles,WILLOW_PARTICLE,self.x,self.y,color,lifetime+0.5,speed,angle)
        elif self.ftype == CRACKLER_FW:
            baseh=random.random()
            bases=0.6
            n+=10
            maxsize = 6+random.random()*3
            for i in range(n):
                h=(baseh+random.random()*0.2)%1
                s=bases+random.random()*0.4
                color = hsv_2_rgb(h, s, 1)
                r=np.sqrt(random.random())*maxsize
                angle = random.random()*360*DEG_2_RAD
                Particle(self.explosion_particles,CRACKLER_PARTICLE,self.x+math.cos(angle)*r,self.y+math.sin(angle)*r,color,lifetime+random.random())


