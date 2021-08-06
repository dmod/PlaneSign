from PIL import Image

image = Image.open(f"/home/pi/PlaneSign/icons/04d.png")
image.thumbnail((22, 22))

image.save("/home/pi/PlaneSign/testout.jpeg", "PNG")