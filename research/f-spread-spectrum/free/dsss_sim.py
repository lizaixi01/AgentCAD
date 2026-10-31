"""F题 简易数字扩频信号收发机：发射端、信道、接收端（捕获 + 跟踪 + A'/B' 输出）全链路仿真。

所有时间都以"真实时间"t（秒）为基准；发射端和接收端各有自己的晶振误差（ppm），
接收端只能看到自己的采样序号 n，并按标称 40 MS/s 理解它。

用法:
    python dsss_sim.py            # 跑全部场景，结果写到 out/
    python dsss_sim.py --code code.txt   # 用附件一的 1000 位 0/1 伪码替换替代码
"""
import argparse
import json
import pathlib
import time

import numpy as np

FC = 4e6          # 标称载波
RC = 1e6          # 码率
N = 1000          # 码周期（chip）
FS = 40e6         # 接收端标称采样率
L = int(FS * 1e-3)  # 每 1 ms 一个处理块（= 一个码周期）
T = 1e-3
FM_DEV, FM_W = 5e3, 0.2   # 变频：fA = 4 MHz + 5 kHz·sin(0.2 t)

OUT = pathlib.Path(__file__).with_name("out")


# ---------------------------------------------------------------- 伪码
def periodic_acf(c):
    f = np.fft.fft(c)
    return np.real(np.fft.ifft(f * np.conj(f))).round().astype(int)


def make_standin_code(seed=2026, target=80):
    """附件一不在手边：爬山搜索一条周期自相关旁瓣 <= target 的 ±1 序列作为替身。"""
    rng = np.random.default_rng(seed)
    c = rng.choice([-1.0, 1.0], N)
    def cost(c):
        r = np.abs(periodic_acf(c)[1:])
        return r.max() * 1e6 + np.sum(np.maximum(r - target + 20, 0) ** 2)
    best = cost(c)
    for _ in range(60000):
        i = rng.integers(N)
        c[i] = -c[i]
        k = cost(c)
        if k <= best:
            best = k
            if np.abs(periodic_acf(c)[1:]).max() <= target - 10:
                break
        else:
            c[i] = -c[i]
    return c


def load_code(path):
    if path:
        bits = [ch for ch in pathlib.Path(path).read_text(encoding="utf8") if ch in "01"]
        assert len(bits) == N, f"附件伪码应为 {N} 位，读到 {len(bits)} 位"
        return np.array([1.0 if b == "0" else -1.0 for b in bits])
    cache = OUT / "standin_code.txt"
    if cache.exists():
        return load_code(cache)
    c = make_standin_code()
    OUT.mkdir(exist_ok=True)
    cache.write_text("".join("0" if v > 0 else "1" for v in c), encoding="utf8")
    return c


# ---------------------------------------------------------------- 发射端 + 信道
class Transmitter:
    """DDS 载波 × 伪码。u 为发射端本地时间（受其晶振 ppm 影响）。"""

    def __init__(self, code, ppm, theta0, chip0, fm, fm_t0):
        self.code, self.k = code, 1 + ppm * 1e-6
        self.theta0, self.chip0, self.fm, self.fm_t0 = theta0, chip0, fm, fm_t0

    def carrier_phase(self, t):
        u = t * self.k
        ph = self.theta0 + 2 * np.pi * FC * u
        if self.fm:   # 相位 = 频率的积分，而不是 2π fA(t) t
            ph += 2 * np.pi * FM_DEV / FM_W * (np.cos(FM_W * self.fm_t0) - np.cos(FM_W * (u + self.fm_t0)))
        return ph

    def carrier_freq(self, t):
        u = t * self.k
        return self.k * (FC + (FM_DEV * np.sin(FM_W * (u + self.fm_t0)) if self.fm else 0.0))

    def code_phase(self, t):          # 码相位（chip，连续值）；码率不随变频改变
        return (self.chip0 + RC * self.k * t) % N

    def C(self, t):
        return self.code[np.floor(self.code_phase(t)).astype(int) % N] * np.cos(self.carrier_phase(t))


# ---------------------------------------------------------------- 接收端
class Receiver:
    def __init__(self, code, ppm, cn0_dbhz, tau_in, tau_out, tau_comp, rng, acq_latency_ms=10,
                 fll_k=0.2, pll_bn=20.0, dll_bn=8.0):
        self.code, self.k = code, 1 + ppm * 1e-6
        self.rng = rng
        self.tau_in, self.tau_out, self.tau_comp = tau_in, tau_out, tau_comp
        self.sigma = np.sqrt(0.5 / 10 ** (cn0_dbhz / 10) * FS / 2)
        self.acq_latency = acq_latency_ms
        self.fll_k, self.pll_bn, self.dll_bn = fll_k, pll_bn, dll_bn
        idx = np.floor(np.arange(L) * RC / FS).astype(int) % N
        self.rep_fft = np.conj(np.fft.fft(code[idx]))
        self.nn = np.arange(L)

    def t_of(self, n):                 # 接收端第 n 个采样的真实时刻
        return n / (FS * self.k)

    def block(self, tx, k, t_on):
        n = k * L + self.nn
        t = self.t_of(n) - self.tau_in
        x = np.where(t >= t_on, tx.C(t - t_on), 0.0)
        return x + self.sigma * self.rng.standard_normal(L)

    # ---- 捕获：对每个频率格做一次 40000 点 FFT 循环相关（长度恰为一个码周期，不补零）
    def corr_surface(self, x, freqs):
        ph = 2 * np.pi * np.outer(FC + freqs, self.nn / FS)
        X = np.fft.fft(x[None, :] * np.exp(-1j * ph), axis=1)
        return np.abs(np.fft.ifft(X * self.rep_fft[None, :], axis=1)) ** 2

    @staticmethod
    def peak_ratio(R):
        i = int(np.argmax(R))
        excl = np.ones_like(R, bool)
        excl[np.arange(i - 60, i + 61) % len(R)] = False
        return i, R[i] / R[excl].max()

    @staticmethod
    def interp(R, i):
        """无带限时相关峰是三角形：对幅度做三角插值（抛物线插值在三角峰上有偏）。"""
        a, b, c = np.sqrt(R[[(i - 1) % len(R), i, (i + 1) % len(R)]])
        return i + 0.5 * (c - a) / (b - min(a, c))

    def run(self, tx, t_on, t_end, start_offset, log_every=1, keep_surface=False):
        """返回状态日志。start_offset：接收端块时钟相对 C 开启的随机偏移。"""
        freqs = np.arange(-5500, 5501, 500.0)
        k = int(np.floor(t_on * FS * self.k / L)) - 1 + int(start_offset)  # 第一个处理块
        log, ev = [], {"t_on": t_on}
        state, acq_tries = "acq", 0
        while True:
            t_blk = self.t_of(k * L)
            if t_blk > t_end:
                break
            if state == "acq":
                acq_tries += 1
                R = sum(self.corr_surface(self.block(tx, k + m, t_on), freqs) for m in range(2))
                fi, ti = np.unravel_index(np.argmax(R), R.shape)
                _, ratio = self.peak_ratio(R[fi])
                if ratio < 3.0:                     # 未检测到：下一块再试
                    k += 2 + self.acq_latency
                    continue
                if keep_surface:
                    ev["surface"] = (freqs, R)
                # 隔 50 ms 在一个完整的块上再做一次全频格相关：
                # 1) 重新选频格并在频格间插值。C 若在块中间开启，首块只含一小段信号，
                #    频率分辨率远粗于 500 Hz，选错频格会让 FLL 落在 1 kHz 的混叠点上；
                # 2) 两次码相位之差给出码速率（两端晶振差），给 DLL 预置。
                D = 50
                S2 = self.corr_surface(self.block(tx, k + D, t_on), freqs)
                fi, t2 = np.unravel_index(np.argmax(S2), S2.shape)
                col = S2[:, t2]
                df_bin = 0.0
                if 0 < fi < len(freqs) - 1:
                    a, b, c = np.sqrt(col[fi - 1:fi + 2])
                    df_bin = 0.5 * (c - a) / (2 * b - a - c) * (freqs[1] - freqs[0])
                R2 = S2[fi]
                ti = int(np.argmax(R[fi]))
                tau1, tau2 = self.interp(R[fi], ti), self.interp(R2, int(t2))
                dtau = (tau2 - tau1 + L / 2) % L - L / 2
                code_rate = RC * (1 - dtau / (D * L))          # chips / (接收端标称秒)
                cp_k = (-tau1 * RC / FS) % N                  # 第 k 块起点的码相位
                f_nco = FC + freqs[fi] + df_bin
                k_trk = k + D + 1 + self.acq_latency          # 把码相位推进到当前时刻再交接
                cp = (cp_k + code_rate * (k_trk - k) * L / FS) % N
                ph = 0.0
                ev.update(acq_detect_t=self.t_of((k + 2) * L), acq_tries=acq_tries,
                          acq_freq=freqs[fi], acq_ratio=float(ratio))
                k = k_trk
                state, dfbuf, fhist, prevP = "fll", [], [], None
                pll_a1 = pll_a2 = 0.0
                dll_int = code_rate - RC
                lockbuf, ecbuf = [], []
                continue

            # ---- 跟踪：E/P/L 三路相关，1 ms 更新
            x = self.block(tx, k, t_on)
            tl = self.nn / FS
            f_used = f_nco
            bb = x * np.exp(-1j * (ph + 2 * np.pi * f_nco * tl))
            fcode = RC + dll_int
            cph = cp + fcode * tl
            E = bb @ self.code[np.floor(cph + 0.5).astype(int) % N]
            P = bb @ self.code[np.floor(cph).astype(int) % N]
            Lt = bb @ self.code[np.floor(cph - 0.5).astype(int) % N]
            # 码环：归一化超前减滞后包络，2 阶环
            e_code = 0.5 * (abs(E) - abs(Lt)) / (abs(E) + abs(Lt))
            w0 = self.dll_bn / 0.53
            dll_int += w0 ** 2 * T * e_code
            code_adj = 1.414 * w0 * e_code
            # 载波环：先 FLL 拉频，再 3 阶 PLL（无数据，用四象限 atan2，无 180° 模糊）
            e_ph = float(np.angle(P))
            if state == "fll":
                if prevP is not None:
                    df = np.angle(P * np.conj(prevP)) / (2 * np.pi * T)
                    f_nco += self.fll_k * df
                    dfbuf.append(df)
                    fhist.append(f_nco)
                    if len(dfbuf) >= 50 and abs(np.mean(dfbuf[-10:])) < 8:   # 前 25 ms 是 FLL 自身的收敛过程
                        # 交给 PLL：频率、频率变化率（变频时最大 1000 Hz/s）都从 FLL 带过去，
                        # NCO 相位一次性对齐，避免从 ±π 附近拉入或 3 阶环慢慢积累斜率时滑周
                        state = "pll"
                        rate = np.polyfit(np.arange(25) * T, fhist[-25:], 1)[0]
                        pll_a1 = 2 * np.pi * rate
                        pll_a2 = 2 * np.pi * (f_nco + np.mean(dfbuf[-10:]) - FC)
                        f_nco = FC + pll_a2 / (2 * np.pi)
                        ph += e_ph
                f_next = f_nco
            else:
                w = self.pll_bn / 0.7845
                pll_a1 += w ** 3 * T * e_ph
                pll_a2 += T * (pll_a1 + 1.1 * w ** 2 * e_ph)
                f_next = FC + (pll_a2 + 2.4 * w * e_ph) / (2 * np.pi)
                lockbuf.append(np.cos(2 * e_ph))
                ecbuf.append(e_code)
                lockbuf, ecbuf = lockbuf[-20:], ecbuf[-20:]
                # 锁定指示：连续 20 ms 的相位锁定度和平均码误差，而不是单次判决
                if "lock_t" not in ev and len(lockbuf) == 20 and np.mean(lockbuf) > 0.9 and abs(np.mean(ecbuf)) < 0.03:
                    ev["lock_t"] = self.t_of((k + 1) * L)
            prevP = P

            # ---- 真值比较（块中点）
            if k % log_every == 0:
                tm = self.t_of(k * L + L / 2)
                rx_ph = ph + 2 * np.pi * f_used * (L / 2) / FS
                true_ph = tx.carrier_phase(tm - self.tau_in - t_on)
                rx_cp = cp + fcode * (L / 2) / FS
                true_cp = tx.code_phase(tm - self.tau_in - t_on)
                e_chip = (rx_cp - true_cp + N / 2) % N - N / 2
                log.append((tm - t_on, state, f_used * self.k, tx.carrier_freq(tm - self.tau_in - t_on),
                            float(np.angle(np.exp(1j * (rx_ph - true_ph)))), e_chip, e_ph, e_code,
                            float(abs(P))))
            ph += 2 * np.pi * f_used * L / FS
            cp = (cp + fcode * L / FS + code_adj * T) % N
            f_nco = f_next
            k += 1
        return log, ev


# ---------------------------------------------------------------- 场景
def scenario(code, seed, fm=False, fm_at=None, cable_m=1.0, cn0=60.0, t_after_on=0.6,
             log_every=1, keep_surface=False):
    rng = np.random.default_rng(seed)
    if fm_at == "peak":      # fA 在 +5 kHz 附近开启
        fm_t0 = np.pi / 2 / FM_W + rng.uniform(-0.3, 0.3)
    elif fm_at == "center":  # 中心频率附近，df/dt 最大
        fm_t0 = rng.uniform(-0.3, 0.3)
    else:
        fm_t0 = rng.uniform(0, 2 * np.pi / FM_W)
    tx = Transmitter(code, ppm=rng.uniform(-30, 30), theta0=rng.uniform(0, 2 * np.pi),
                     chip0=rng.uniform(0, N), fm=fm, fm_t0=fm_t0)
    tau_cable = 5e-9 * cable_m          # 同轴电缆约 5 ns/m
    tau_afe, tau_out = 150e-9, 60e-9    # 模拟前端+ADC+流水线、码 NCO→DAC→B' 的固定延迟（标定量）
    tau_comp = 5e-9 * 1.5 + tau_afe + tau_out   # 按 1.5 m 电缆的中值做一次性标定
    rx = Receiver(code, ppm=rng.uniform(-30, 30), cn0_dbhz=cn0, tau_in=tau_cable + tau_afe,
                  tau_out=tau_out, tau_comp=tau_comp, rng=rng)
    t_on = rng.uniform(0.002, 0.004)
    log, ev = rx.run(tx, t_on, t_on + t_after_on, start_offset=rng.integers(0, 3),
                     log_every=log_every, keep_surface=keep_surface)
    # B' 相对 B 的时间误差：跟踪误差 + 未补偿的固定延迟 + 40 MS/s 输出量化
    q = rng.uniform(-12.5e-9, 12.5e-9, len(log))
    fixed = rx.tau_in + rx.tau_out - rx.tau_comp
    berr = np.array([-row[5] / RC + fixed for row in log]) + q
    return tx, rx, log, ev, berr


def summarize(log, ev, berr):
    lock = ev.get("lock_t")
    rows = [r for r in log if lock is not None and r[0] >= lock - ev["t_on"]]
    b = berr[-len(rows):] if rows else np.array([np.nan])
    ph = np.unwrap([r[4] for r in rows]) if rows else np.array([np.nan])
    return {
        "acq_tries": ev.get("acq_tries"),
        "t_detect_s": (ev["acq_detect_t"] - ev["t_on"]) if "acq_detect_t" in ev else None,
        "t_lock_s": (lock - ev["t_on"]) if lock else None,
        "b_err_max_ns": float(np.nanmax(np.abs(b)) * 1e9),
        "b_err_rms_ns": float(np.sqrt(np.nanmean(b ** 2)) * 1e9),
        "a_phase_drift_rad": float(np.nanmax(ph) - np.nanmin(ph)),
        "f_err_max_hz": float(max(abs(r[2] - r[3]) for r in rows)) if rows else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code")
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--long", type=float, default=32.0, help="变频长时跟踪仿真时长（s）")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    code = load_code(a.code)
    acf = periodic_acf(code)
    res = {"code": {"source": a.code or "stand-in (附件一缺失)", "peak": int(acf[0]),
                    "max_sidelobe": int(np.abs(acf[1:]).max())}}
    print("code", res["code"])
    np.save(OUT / "acf.npy", acf)

    cases = [
        ("固定载波 1 m 电缆", dict(cable_m=1.0)),
        ("固定载波 2 m 电缆", dict(cable_m=2.0)),
        ("固定载波 低 C/N0 45 dB-Hz", dict(cn0=45.0)),
        ("变频 在频率峰值开启", dict(fm=True, fm_at="peak")),
        ("变频 在中心频率开启", dict(fm=True, fm_at="center")),
    ]
    res["cases"] = {}
    t0 = time.time()
    for name, kw in cases:
        out = []
        for s in range(a.trials):
            _, _, log, ev, berr = scenario(code, seed=1000 * len(res["cases"]) + s, **kw)
            out.append(summarize(log, ev, berr))
        res["cases"][name] = out
        lk = [o["t_lock_s"] for o in out if o["t_lock_s"] is not None]
        print(f"{name}: lock {len(lk)}/{len(out)}  max t_lock {max(lk):.3f}s  "
              f"max|B'-B| {max(o['b_err_max_ns'] for o in out):.1f} ns  ({time.time() - t0:.0f}s)")

    # 代表性运行，保存完整日志与捕获面用于作图
    _, _, log, ev, berr = scenario(code, seed=7, keep_surface=True)
    f, R = ev.pop("surface")
    np.savez(OUT / "demo_fixed.npz", log=np.array([r[:1] + r[2:] for r in log], float),
             state=np.array([r[1] for r in log]), berr=berr, freqs=f, R=R)
    res["demo_fixed"] = {**summarize(log, ev, berr), **{k: v for k, v in ev.items() if k != "t_on"}}

    _, _, log, ev, berr = scenario(code, seed=11, fm=True, fm_at="center", t_after_on=a.long, log_every=1)
    np.savez(OUT / "demo_fm_long.npz", log=np.array([r[:1] + r[2:] for r in log], float),
             state=np.array([r[1] for r in log]), berr=berr)
    res["demo_fm_long"] = summarize(log, ev, berr)
    print("long FM", res["demo_fm_long"], f"({time.time() - t0:.0f}s)")
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf8")


if __name__ == "__main__":
    main()
