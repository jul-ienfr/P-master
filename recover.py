import subprocess

try:
    data = subprocess.check_output(['git', 'show', '1fa5f926241e039f214c5daf4cdce6f1171768d9:src/bot/action_controller.py'])
    with open('src/bot/action_controller.py', 'wb') as f:
        f.write(data)
    print("Success")
except Exception as e:
    print(e)
