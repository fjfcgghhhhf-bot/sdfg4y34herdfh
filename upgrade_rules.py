"""Server-side weighted upgrade draw with a visually narrow bonus sector.

Ordinary win chance controls the size of the lower arc. Bonus appearance and
bonus hit are two independent 30% trials; endpoint sampling then makes the
animation land inside the region corresponding to the already chosen result.
"""
import secrets
from protocol import percent

def _angle_in(intervals,randbelow):
    """Sample open interval interiors so boundary pixels never contradict result."""
    widths=[max(0,end-start) for start,end in intervals]
    total=sum(widths)
    if total<=0: raise ValueError('Нет допустимого сектора апгрейдера.')
    distance=(randbelow(1_000_000)+.5)/1_000_000*total
    for (start,end),width in zip(intervals,widths):
        if distance<width: return (start+distance)%360
        distance-=width
    return (intervals[-1][1]-1e-6)%360

def roll_upgrade(chance,randbelow=None):
    chance=percent(chance,'Шанс апгрейдера')
    rng=randbelow or secrets.randbelow
    half_win=1.8*chance
    # Always leave some ordinary winning region, even at 1%.
    target_half_width=min(8.0,half_win*.25) if chance else 8.0
    special=rng(100)<30
    hit=special and rng(100)<30
    if hit:
        result='immune'; intervals=[(90-target_half_width,90+target_half_width)]
    else:
        win=rng(100)<chance
        result='win' if win else 'loss'
        if win:
            intervals=([(90-half_win,90-target_half_width),(90+target_half_width,90+half_win)]
                       if special else [(90-half_win,90+half_win)])
        else:
            # Unwrap around the bottom centre. At 0% the bonus target is the
            # sole coloured region and must be excluded from losing endpoints.
            excluded=max(half_win,target_half_width if special else 0)
            intervals=[(90+excluded,450-excluded)]
    return {'result':result,'angle':_angle_in(intervals,rng),'special':special,
            'chance':chance,'target_half_width':target_half_width}
