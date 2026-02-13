def __init__(self):
    self.players = []
    self.current_player_index = 0
    self.game_state = "waiting"  # waiting, playing, finished
    self.winner = None
    self.turn_count = 0