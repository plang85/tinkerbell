import tinkerbell.app.plot as tbapl
import tinkerbell.domain.point as tbdpt
import tinkerbell.domain.make as tbdmk
import tinkerbell.domain.curve as tbdcv
import tinkerbell.app.make as tbamk
import tinkerbell.app.rcparams as tbarc
import pandas as pd
import numpy as np

XDISC_MIN = 20.0
XDISC_MAX = 30.0
PMAX = 6
D = 0.1


def do_the_thing():
    num_xdisc = 30
    num_realizations = 30
    xdiscspace = (XDISC_MIN, XDISC_MAX)
    y0_mean = tbarc.rcparams['shale.exp.y0_mean']
    d = D
    k = tbarc.rcparams['shale.exp.k']
    pmax = PMAX
    xmax = 2.0**pmax
    dx = tbarc.rcparams['shale.exp.dx']

    num_knots = tbdmk.num_knots_curve_lsq(k, tbarc.rcparams['shale.exp.num_knots_internal'])
    columns = ('y0', 'xdisc', *tbdcv.flat_header(num_knots, num_knots))
    data = pd.DataFrame(0.0, index=np.arange(num_xdisc*num_realizations), columns=columns)

    idatarow = 0
    np.random.seed(42)
    for xdisc in np.linspace(*xdiscspace, num_xdisc):
        for irealization in range(num_realizations):
            y0 = y0_mean
            pts, _ = tbamk.points_exponential_discontinuous_declinebase2_noisy(y0, d, pmax, xdisc)
            t = tbamk.knots_internal_four_heavy_right(xdisc, xmax, dx)
            crv = tbdmk.curve_lsq_fixed_knots(pts, t, k)

            if 0:
                tbapl.plot([tbdpt.point_coordinates(pts), crv.xycoordinates()], ['p', 'l'], hide_labels=True,
                    ylabel='production', xlabel='time')

            data.iat[idatarow, 0] = y0
            data.iat[idatarow, 1] = xdisc
            data.loc[idatarow, 2:] = crv.to_flat() 
            idatarow += 1

    data.to_csv(tbarc.rcparams['shale.exp.csvsplinefname'], index=False)


if __name__ == '__main__':
  do_the_thing()