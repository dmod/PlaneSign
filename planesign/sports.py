from pyowm import OWM
from PIL import Image
import utilities
import logging
import time
import requests
import shared_config
import __main__
from rgbmatrix import graphics
from modes import DisplayMode

@__main__.planesign_mode_handler(DisplayMode.SPORTS_BALL)
def show_sports(sign):

    while shared_config.shared_mode.value == DisplayMode.SPORTS_BALL:

        sign.canvas.Clear()

        espn_response = requests.get(f"https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=football&league=nfl")
        if espn_response and espn_response.status_code == requests.codes.ok:
            espn_json = espn_response.json()['sports']
            leagues = next(filter(lambda x: x['name'] == 'Football', espn_json))['leagues']
            nfl = next(filter(lambda x: x['abbreviation'] == 'NFL', leagues))

            first_event = nfl['events'][0]

            first_team = first_event['competitors'][0]
            second_team = first_event['competitors'][1]

            with open('team_1.png', 'wb') as f:
                f.write(requests.get(first_team['logo']).content)

            with open('team_2.png', 'wb') as f:
                f.write(requests.get(second_team['logo']).content)

            image1 = Image.open(f"team_1.png").convert('RGB')
            image1 = image1.resize((40, 40), Image.BICUBIC)

            image2 = Image.open(f"team_2.png").convert('RGB')
            image2 = image2.resize((40, 40), Image.BICUBIC).convert('RGB')

            sign.canvas.SetImage(image1, 20, 1)
            sign.canvas.SetImage(image2, 80, 1)

            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        breakout = sign.wait_loop(30)
        if breakout:
            return
