import sys, os
from vncdotool import api
V = open("/home/ubuntu/.config/fatfish-sentinel/vnc_pass").read().strip()
c = api.connect("127.0.0.1::5900", password=V)
x, y = int(sys.argv[1]), int(sys.argv[2])
c.mouseMove(x, y)
c.mousePress(1)
c.pause(0.5)
os._exit(0)
