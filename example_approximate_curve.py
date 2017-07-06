import tinkerbell.domain.point as tbdpt
import tinkerbell.domain.make as tbdmk
import tinkerbell.app.plot as tbapl


pts = tbdpt.read_points('data_demo/points_02.json')

xmax = 50.0
xdisc = 20.0
dx = xmax/50
k = 2
t = tbdmk.knots_four_heavy_right(xdisc, xmax, dx)
crv = tbdmk.curve_lsq_fixed_knots(pts, t, k)

tbapl.plot_points_curves([(pts, crv)])