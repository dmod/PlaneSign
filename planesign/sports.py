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

def draw_text_with_background(canvas, font, x, y, text, color, bg_color):
    """Draw text with a colored background box"""
    # Calculate text width and height
    text_width = len(text) * 6  # Approximate width for font57
    text_height = 7  # Height for font57
    
    # Draw background box (slightly larger than text)
    for i in range(x-1, x + text_width + 1):
        for j in range(y-text_height, y+1):
            canvas.SetPixel(i, j, bg_color[0], bg_color[1], bg_color[2])
    
    # Draw text
    graphics.DrawText(canvas, font, x, y, color, text)

@__main__.planesign_mode_handler(DisplayMode.SPORTS_BALL)
def show_sports(sign):
    while shared_config.shared_mode.value == DisplayMode.SPORTS_BALL.value:
        sign.canvas.Clear()
        
        try:
            espn_response = requests.get("https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=football&league=nfl")
            if espn_response and espn_response.status_code == requests.codes.ok:
                espn_json = espn_response.json()['sports']
                leagues = next(filter(lambda x: x['name'] == 'Football', espn_json))['leagues']
                nfl = next(filter(lambda x: x['abbreviation'] == 'NFL', leagues))
                
                if not nfl['events']:
                    # No games currently - show message
                    graphics.DrawText(sign.canvas, sign.font57, 45, 12, graphics.Color(255, 0, 0), "No NFL")
                    graphics.DrawText(sign.canvas, sign.font57, 45, 22, graphics.Color(255, 0, 0), "Games")
                else:
                    first_event = nfl['events'][0]
                    team1 = first_event['competitors'][0]
                    team2 = first_event['competitors'][1]
                    game_status = first_event['fullStatus']['type']
                    
                    # Convert hex colors to RGB
                    def hex_to_rgb(hex_color):
                        hex_color = hex_color.lstrip('#')
                        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                    
                    team1_color = hex_to_rgb(team1.get('color', '000000'))
                    team2_color = hex_to_rgb(team2.get('color', '000000'))
                    
                    # Download and display team logos
                    try:
                        logo1_url = team1.get('team', {}).get('logos', [{}])[0].get('href', '')
                        logo2_url = team2.get('team', {}).get('logos', [{}])[0].get('href', '')
                        
                        if logo1_url and logo2_url:
                            with open('.data/team1_logo.png', 'wb') as f:
                                f.write(requests.get(logo1_url).content)
                            with open('.data/team2_logo.png', 'wb') as f:
                                f.write(requests.get(logo2_url).content)
                            
                            image1 = Image.open(".data/team1_logo.png").convert('RGB')
                            image1 = image1.resize((24, 24), Image.BICUBIC)
                            image2 = Image.open(".data/team2_logo.png").convert('RGB')
                            image2 = image2.resize((24, 24), Image.BICUBIC)
                            
                            sign.canvas.SetImage(image1, 2, 4)
                            sign.canvas.SetImage(image2, 102, 4)
                    except Exception as e:
                        logging.error(f"Error loading team logos: {e}")
                    
                    # Draw team abbreviations with colored backgrounds
                    draw_text_with_background(
                        sign.canvas, sign.font57, 28, 12, 
                        team1['abbreviation'], 
                        graphics.Color(255, 255, 255),  # White text
                        team1_color
                    )
                    draw_text_with_background(
                        sign.canvas, sign.font57, 75, 12, 
                        team2['abbreviation'], 
                        graphics.Color(255, 255, 255),  # White text
                        team2_color
                    )

                    # Draw scores or game time
                    if game_status['state'] == 'pre':
                        game_time = game_status['shortDetail'][:8]
                        text_width = len(game_time) * 6
                        x_pos = (128 - text_width) // 2
                        graphics.DrawText(sign.canvas, sign.font57, x_pos, 25, graphics.Color(0, 255, 0), game_time)
                    else:
                        score1 = team1.get('score', '0')
                        score2 = team2.get('score', '0')
                        
                        graphics.DrawText(sign.canvas, sign.fontbig, 28, 25, graphics.Color(255, 255, 0), score1)
                        graphics.DrawText(sign.canvas, sign.fontbig, 75, 25, graphics.Color(255, 255, 0), score2)
                        
                        status_text = game_status['shortDetail'][:8]
                        text_width = len(status_text) * 6
                        x_pos = (128 - text_width) // 2
                        graphics.DrawText(sign.canvas, sign.font57, x_pos, 31, graphics.Color(0, 255, 0), status_text)

            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            
        except Exception as e:
            logging.error(f"Error in sports display: {e}")
            time.sleep(5)

        breakout = sign.wait_loop(30)
        if breakout:
            return
