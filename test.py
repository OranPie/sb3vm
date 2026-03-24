import base64

from sb3vm.codegen import (
    EDGE,
    GraphicEffect,
    LayerDirection,
    LayerPosition,
    MOUSE_POINTER,
    MYSELF,
    RANDOM_POSITION,
    RotationStyle,
    ScratchProject,
    StopTarget,
    answer,
    join,
    key_pressed,
    letter_of,
    math_op,
    mouse_down,
    mouse_x,
    mouse_y,
    random_between,
    round_value,
    string_contains,
    string_length,
    timer,
)

project = ScratchProject('0.2.0-prerelease.20200602151852')
stage = project.stage
project.extensions.append('music')
project.register_broadcast('notes')
project.add_asset('2b2d1ab1ed7ddd1aee42c5f40558027f.svg', base64.b64decode('PHN2ZyB2ZXJzaW9uPSIxLjEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHdpZHRoPSI1NTQiIGhlaWdodD0iNDAwIiB2aWV3Qm94PSIwLDAsNTU0LDQwMCI+PGcgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoMzcsMjApIj48ZyBkYXRhLXBhcGVyLWRhdGE9InsmcXVvdDtpc1BhaW50aW5nTGF5ZXImcXVvdDs6dHJ1ZX0iIGZpbGw9IiNmZmZmZmYiIGZpbGwtcnVsZT0ibm9uemVybyIgc3Ryb2tlPSJub25lIiBzdHJva2UtbGluZWNhcD0iYnV0dCIgc3Ryb2tlLWxpbmVqb2luPSJtaXRlciIgc3Ryb2tlLW1pdGVybGltaXQ9IjEwIiBzdHJva2UtZGFzaGFycmF5PSIiIHN0cm9rZS1kYXNob2Zmc2V0PSIwIiBzdHlsZT0ibWl4LWJsZW5kLW1vZGU6IG5vcm1hbCI+PHBhdGggZD0iTS0zNywzODB2LTQwMGg1NTR2NDAweiIgc3Ryb2tlLXdpZHRoPSIwIi8+PHRleHQgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoNTkuNSw4My4xNDk5OSkgc2NhbGUoMC41LDAuNSkiIGZvbnQtc2l6ZT0iNDAiIHhtbDpzcGFjZT0icHJlc2VydmUiIGZpbGw9IiNmZmZmZmYiIGZpbGwtcnVsZT0ibm9uemVybyIgc3Ryb2tlPSJub25lIiBzdHJva2Utd2lkdGg9IjEiIHN0cm9rZS1saW5lY2FwPSJidXR0IiBzdHJva2UtbGluZWpvaW49Im1pdGVyIiBzdHJva2UtbWl0ZXJsaW1pdD0iMTAiIHN0cm9rZS1kYXNoYXJyYXk9IiIgc3Ryb2tlLWRhc2hvZmZzZXQ9IjAiIGZvbnQtZmFtaWx5PSJTYW5zIFNlcmlmIiBmb250LXdlaWdodD0ibm9ybWFsIiB0ZXh0LWFuY2hvcj0ic3RhcnQiIHN0eWxlPSJtaXgtYmxlbmQtbW9kZTogbm9ybWFsIj48dHNwYW4geD0iMCIgZHk9IjAiPuWOn+S9nO+8mlN1bW1lckNpdHk8L3RzcGFuPjx0c3BhbiB4PSIwIiBkeT0iNDYuMTVweCI+5rC05Y2w5Zyo6L+Z77yBPC90c3Bhbj48L3RleHQ+PC9nPjwvZz48L3N2Zz4='))
project.add_asset('83a9787d4cb6f3b7632b4ddfebf74367.wav', base64.b64decode('UklGRigCAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQCAADVAAMDvQdyDe8VUx08I5sk4iCrFnMGVfFf2mDEjbNpqZKo5bFHxUHh8wLtJtFHSmF9byNwCmHOROodKvMPyWqn/ZElje6YObXo3eIMnTpEYHB2tXmiaNhFZxdK5Gy1epLegWuGcZ+OyCH84jB9Xd955H83calNthyp50+4jJYDiWmRT6712VwMADxQX+9vF2lWTgokcfJZxWejtpN4mfiyaNqjCY42a1cpZqJfvEb1H8jyA8r1rc6iH6syxPHqwBSrOShR8VY0SU4rAwQs27667KgOqdG8jN28BjwugEsUWSdSXTmsExzqccWtrSmnurMb0LD2pR56P8hRylFrP30f5/nT1oG+H7ZVvqzVvPUqGIIz9UGEQCwvDBNX8p/Vs8P1v3TLnON6AnogiTaGP9I4OiTDBpLnG86GvwjAFc9R6WsIfiUgOghBtTiWI1MGL+hWzyrC6sJa0QXqSQeUItc10DzsNUojWglH7hvYd8sNy2bWb+qxApIZMyp4MKorPB30CGTzv+G41/bWrN8Q780BKRNcH6gjSB+rE68DUvNw5rrf2+Az6cz2JAbbE/IcSh+EGskPfAHk8jXnDeGG4XroZ/ShAiwQXxoQH4wdXhY9C3T+5/LK6pbnhOng7/n41AIIC0oQkhHZDjcJGQJ5+532lvTd9df5H/+OBJcIFwqKCFUEYf4='))
project.add_asset('a752c5630957247089020f2d99774eb4.svg', base64.b64decode('PHN2ZyB2ZXJzaW9uPSIxLjEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHdpZHRoPSIzOS4zMzMzMyIgaGVpZ2h0PSIzOS4zMzMzMyIgdmlld0JveD0iMCwwLDM5LjMzMzMzLDM5LjMzMzMzIj48ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgtMjIwLjMzMzMzLC0xNjAuMzMzMzMpIj48ZyBkYXRhLXBhcGVyLWRhdGE9InsmcXVvdDtpc1BhaW50aW5nTGF5ZXImcXVvdDs6dHJ1ZX0iIGZpbGwtcnVsZT0ibm9uemVybyIgc3Ryb2tlPSIjMDAwMDAwIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lam9pbj0ibWl0ZXIiIHN0cm9rZS1taXRlcmxpbWl0PSIxMCIgc3Ryb2tlLWRhc2hhcnJheT0iIiBzdHJva2UtZGFzaG9mZnNldD0iMCIgc3R5bGU9Im1peC1ibGVuZC1tb2RlOiBub3JtYWwiPjxwYXRoIGQ9Ik0yMjEuMzMzMzMsMTgwYzAsLTEwLjMwOTMyIDguMzU3MzUsLTE4LjY2NjY3IDE4LjY2NjY3LC0xOC42NjY2N2MxMC4zMDkzMiwwIDE4LjY2NjY3LDguMzU3MzUgMTguNjY2NjcsMTguNjY2NjdjMCwxMC4zMDkzMiAtOC4zNTczNSwxOC42NjY2NyAtMTguNjY2NjcsMTguNjY2NjdjLTEwLjMwOTMyLDAgLTE4LjY2NjY3LC04LjM1NzM1IC0xOC42NjY2NywtMTguNjY2Njd6IiBmaWxsPSIjOTk2NmZmIiBzdHJva2UtbGluZWNhcD0iYnV0dCIvPjxwYXRoIGQ9Ik0yNTguMjUsMTgwaC0xOC4xNjY2NyIgZmlsbD0ibm9uZSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+PC9nPjwvZz48L3N2Zz4='))
project.add_asset('e7fb645bb99a7bef00bb797b618ebe7a.svg', base64.b64decode('PHN2ZyB2ZXJzaW9uPSIxLjEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHdpZHRoPSIzOS4zMzMzNCIgaGVpZ2h0PSIzOS4zMzMzNCIgdmlld0JveD0iMCwwLDM5LjMzMzM0LDM5LjMzMzM0Ij48ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgtMjIwLjMzMzMzLC0xNjAuMzMzMzMpIj48ZyBkYXRhLXBhcGVyLWRhdGE9InsmcXVvdDtpc1BhaW50aW5nTGF5ZXImcXVvdDs6dHJ1ZX0iIGZpbGwtcnVsZT0ibm9uemVybyIgc3Ryb2tlPSIjMDAwMDAwIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lam9pbj0ibWl0ZXIiIHN0cm9rZS1taXRlcmxpbWl0PSIxMCIgc3Ryb2tlLWRhc2hhcnJheT0iIiBzdHJva2UtZGFzaG9mZnNldD0iMCIgc3R5bGU9Im1peC1ibGVuZC1tb2RlOiBub3JtYWwiPjxwYXRoIGQ9Ik0yMjEuMzMzMzMsMTgwYzAsLTEwLjMwOTMyIDguMzU3MzUsLTE4LjY2NjY3IDE4LjY2NjY3LC0xOC42NjY2N2MxMC4zMDkzMiwwIDE4LjY2NjY3LDguMzU3MzUgMTguNjY2NjcsMTguNjY2NjdjMCwxMC4zMDkzMiAtOC4zNTczNSwxOC42NjY2NyAtMTguNjY2NjcsMTguNjY2NjdjLTEwLjMwOTMyLDAgLTE4LjY2NjY3LC04LjM1NzM1IC0xOC42NjY2NywtMTguNjY2Njd6IiBmaWxsPSIjNjZjN2ZmIiBzdHJva2UtbGluZWNhcD0iYnV0dCIvPjxwYXRoIGQ9Ik0yNTguMjUsMTgwaC0xOC4xNjY2NyIgZmlsbD0ibm9uZSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+PC9nPjwvZz48L3N2Zz4='))

stage.add_costume({'assetId': '2b2d1ab1ed7ddd1aee42c5f40558027f', 'name': '背景1', 'bitmapResolution': 1, 'md5ext': '2b2d1ab1ed7ddd1aee42c5f40558027f.svg', 'dataFormat': 'svg', 'rotationCenterX': 277, 'rotationCenterY': 200})
stage.add_sound({'assetId': '83a9787d4cb6f3b7632b4ddfebf74367', 'name': '啵', 'dataFormat': 'wav', 'format': '', 'rate': 44100, 'sampleCount': 1032, 'md5ext': '83a9787d4cb6f3b7632b4ddfebf74367.wav'})
buttons = project.sprite('Buttons', x=-120.0, y=-192.0, visible=False, current_costume=0)
buttons.direction = 0.0
buttons.size = 140.0
buttons.layer_order = 1
buttons.add_costume({'assetId': 'a752c5630957247089020f2d99774eb4', 'name': '90', 'bitmapResolution': 1, 'md5ext': 'a752c5630957247089020f2d99774eb4.svg', 'dataFormat': 'svg', 'rotationCenterX': 19.666666666666657, 'rotationCenterY': 19.666666666666657})
buttons.add_costume({'assetId': 'e7fb645bb99a7bef00bb797b618ebe7a', 'name': '-90', 'bitmapResolution': 1, 'md5ext': 'e7fb645bb99a7bef00bb797b618ebe7a.svg', 'dataFormat': 'svg', 'rotationCenterX': 19.666666666666657, 'rotationCenterY': 19.666666666666657})
buttons.add_sound({'assetId': '83a9787d4cb6f3b7632b4ddfebf74367', 'name': '啵', 'dataFormat': 'wav', 'format': '', 'rate': 44100, 'sampleCount': 1032, 'md5ext': '83a9787d4cb6f3b7632b4ddfebf74367.wav'})

steps = stage.variable('Steps', 0)
score = stage.variable('Score', 4410)
highest = stage.variable('Highest', 10800)
steping = stage.variable('Steping?', '0')
next_but = stage.variable('next but', '05')
notes = stage.variable('notes', '48')
cur_dir = stage.list('cur_dir', [180, 180, 180, 180, 90, 270, 270, 270, 270, 90, 180, 180, 180, 180, 90, 180, 180, 180, 180, 90, 180, 180, 180, 180, 90])
turning_deg = stage.list('turning_deg', ['90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90', '90'])
buttons_but_idx = buttons.variable('but_idx', 26)

@buttons.procedure(warp=True, proccode='Check Highest', argument_names=(), argument_defaults=())
def proc_buttons_check_highest():
    if (score > highest):
        highest = score

@buttons.procedure(warp=True, proccode='增加“next but”为两位数', argument_names=(), argument_defaults=())
def proc_buttons_增加_next_but_为两位数():
    if (string_length(next_but) < 2):
        for _ in range((2 - string_length(next_but))):
            next_but = join(0, next_but)

@buttons.procedure(warp=False, proccode='旋转 %s %s %s', argument_names=('idx', 'deg', 'times'), argument_defaults=('', '', ''))
def proc_buttons_旋转(idx, deg, times):
    score += 90
    proc_buttons_check_highest()
    buttons.broadcast('notes')
    notes += 1
    notes = (((notes - 48) % 36) + 48)
    for _ in range(times):
        cur_dir.replace(idx, ((cur_dir.item(idx) + (deg / times)) % 360))
    if (cur_dir.item(idx) == 90):
        next_but = (idx + 1)
        proc_buttons_增加_next_but_为两位数()
        if (not string_contains('06 11 16 21 26', next_but)):
            proc_buttons_旋转(next_but, turning_deg.item(next_but), 9)
    else:
        if (cur_dir.item(idx) == 180):
            next_but = (idx + 5)
            proc_buttons_增加_next_but_为两位数()
            if (not string_contains('26 27 28 29 30', next_but)):
                proc_buttons_旋转(next_but, turning_deg.item(next_but), 9)
        else:
            if (cur_dir.item(idx) == 270):
                next_but = (idx + -1)
                proc_buttons_增加_next_but_为两位数()
                if (not string_contains('00 05 10 15 20', next_but)):
                    proc_buttons_旋转(next_but, turning_deg.item(next_but), 9)
            else:
                next_but = (idx + -5)
                proc_buttons_增加_next_but_为两位数()
                if (not string_contains('-4 -3 -2 -1 00', next_but)):
                    proc_buttons_旋转(next_but, turning_deg.item(next_but), 9)

@buttons.when_flag_clicked()
def on_buttons_green_flag__1():
    score = 0
    steps = 10
    steping = 0
    notes = 48
    buttons.hide()
    cur_dir.clear()
    turning_deg.clear()
    buttons.set_size(140)
    buttons_but_idx = 1
    buttons.goto_xy(-120, 100)
    buttons.point_in_direction(0)
    for _ in range(5):
        buttons.switch_costume('90')
        for _ in range(5):
            cur_dir.append(0)
            turning_deg.append(buttons.costume_name())
            buttons.create_clone(MYSELF)
            buttons.next_costume()
            buttons.change_x_by(60)
            buttons_but_idx += 1
        buttons.set_x(-120)
        buttons.change_y_by(-60)

@buttons.when_started_as_clone()
def on_buttons_clone_start__2():
    buttons.set_effect(GraphicEffect.GHOST, 100)
    buttons.set_size(100)
    buttons.show()
    for _ in range(10):
        buttons.change_effect_by(GraphicEffect.GHOST, -10)
        buttons.change_size_by(4)
    while True:
        if (steps > 0):
            if buttons.touching_object(MOUSE_POINTER):
                buttons.set_effect(GraphicEffect.BRIGHTNESS, 25)
                if mouse_down():
                    if (steping == 0):
                        steping = 1
                        steps += -1
                        proc_buttons_旋转(buttons_but_idx, turning_deg.item(buttons_but_idx), 9)
                        steping = 0
                        notes = 48
            else:
                buttons.set_effect(GraphicEffect.BRIGHTNESS, 0)
        else:
            buttons.set_effect(GraphicEffect.BRIGHTNESS, 0)

@buttons.when_started_as_clone()
def on_buttons_clone_start__3():
    while True:
        buttons.point_in_direction(cur_dir.item(buttons_but_idx))

@buttons.when_broadcast_received('notes')
def on_buttons_broadcast_received_notes_4():
    buttons.play_note_for_beats(notes, 0.25)
