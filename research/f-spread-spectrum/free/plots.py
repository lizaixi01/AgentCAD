"""把 dsss_sim.py 的结果画成图（out/*.png）。"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import dsss_sim as d

plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei"], "axes.unicode_minus": False,
                     "figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.3})
OUT = d.OUT
res = json.loads((OUT / "results.json").read_text(encoding="utf8"))
code = d.load_code(None)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name)
    plt.close(fig)


# 1 伪码周期自相关
acf = np.load(OUT / "acf.npy")
fig, ax = plt.subplots(figsize=(8, 3))
ax.plot(np.arange(-500, 500), np.roll(acf, 500), lw=0.8)
ax.axhline(80, ls="--", c="r", lw=0.8)
ax.axhline(-80, ls="--", c="r", lw=0.8)
ax.set(title=f"伪码周期自相关：主峰 {acf[0]}，最大旁瓣 {np.abs(acf[1:]).max()}（附件要求的序列：1000 / 80）",
       xlabel="码片位移", ylabel="R(τ)")
save(fig, "1_acf.png")

# 2 发射端波形（前 20 chip）与 C 的频谱
tx = d.Transmitter(code, 0, 0, 0, False, 0)
t = np.arange(0, 20e-6, 1 / 400e6)
fig, axs = plt.subplots(3, 1, figsize=(9, 5), sharex=True)
axs[0].plot(t * 1e6, np.cos(tx.carrier_phase(t)), lw=0.6)
axs[0].set_ylabel("A 载波")
axs[1].step(t * 1e6, code[np.floor(tx.code_phase(t)).astype(int)], lw=0.9, where="post")
axs[1].set_ylabel("B 伪码")
axs[2].plot(t * 1e6, tx.C(t), lw=0.6)
axs[2].set(ylabel="C 扩频", xlabel="时间 (µs)")
axs[0].set_title("发射端输出：前 20 个码片")
save(fig, "2_tx_waveforms.png")

t = np.arange(0, 10e-3, 1 / d.FS)
c = tx.C(t)
f = np.fft.rfftfreq(len(c), 1 / d.FS)
P = np.abs(np.fft.rfft(c * np.hanning(len(c)))) ** 2
k = 200
Ps = np.convolve(P, np.ones(k) / k, "same")
fig, ax = plt.subplots(figsize=(8, 3))
ax.plot(f / 1e6, 10 * np.log10(Ps / Ps.max()), lw=0.8)
ax.set(xlim=(0, 10), ylim=(-50, 2), xlabel="频率 (MHz)", ylabel="dB",
       title="C 的功率谱：4 MHz 为中心，主瓣 ±1 MHz（sinc²）")
save(fig, "3_c_spectrum.png")

# 3 捕获面
z = np.load(OUT / "demo_fixed.npz")
R = z["R"]
fi = np.argmax(R.max(1))
fig, axs = plt.subplots(1, 2, figsize=(10, 3.2))
axs[0].imshow(10 * np.log10(R / R.max()), aspect="auto", origin="lower", vmin=-30, cmap="viridis",
              extent=[0, 1000, z["freqs"][0] / 1e3 - 0.25, z["freqs"][-1] / 1e3 + 0.25])
axs[0].set(xlabel="码相位 (chip)", ylabel="频偏 (kHz)", title="|R(τ,f)|² 捕获面 (dB)")
axs[1].plot(np.arange(R.shape[1]) / 40, R[fi] / R[fi].max(), lw=0.6)
axs[1].set(xlabel="码相位 (chip)", title=f"最佳频格 {z['freqs'][fi]:+.0f} Hz 的切片")
save(fig, "4_acquisition.png")

# 4 代表性跟踪过渡（固定载波）
lg = z["log"]   # t, f_nco, f_true, dph, e_chip, e_ph, e_code, |P|
st = z["state"]
tt = lg[:, 0] * 1e3
fig, axs = plt.subplots(3, 1, figsize=(9, 6.5), sharex=True)
for s, col in (("fll", "C1"), ("pll", "C0")):
    m = st == s
    axs[0].plot(tt[m], lg[m, 1] - lg[m, 2], ".", ms=2, c=col, label=s.upper())
axs[0].set(ylabel="NCO − 真实频率 (Hz)", ylim=(-150, 150))
axs[0].legend()
axs[1].plot(tt, lg[:, 3], lw=0.8)
axs[1].set(ylabel="A′−A 相位差 (rad)")
axs[2].plot(tt, z["berr"] * 1e9, lw=0.6)
axs[2].axhspan(-200, 200, color="g", alpha=0.08)
axs[2].set(ylabel="B′−B (ns)", xlabel="C 开启后时间 (ms)", ylim=(-250, 250))
lock = res["demo_fixed"]["t_lock_s"] * 1e3
for a in axs:
    a.axvline(lock, c="r", ls="--", lw=0.8)
axs[0].set_title(f"固定载波：捕获 → FLL → PLL，{lock:.0f} ms 锁定（红线）")
save(fig, "5_tracking_fixed.png")

# 5 变频长时跟踪（一个完整周期 31.4 s）
z2 = np.load(OUT / "demo_fm_long.npz")
lg2 = z2["log"]
m = z2["state"] == "pll"
fig, axs = plt.subplots(3, 1, figsize=(9, 6.5), sharex=True)
axs[0].plot(lg2[:, 0], (lg2[:, 2] - d.FC) / 1e3, lw=1, label="真实 fA − 4 MHz")
axs[0].plot(lg2[m, 0][::50], (lg2[m, 1][::50] - d.FC) / 1e3, ".", ms=2, label="接收端载波 NCO")
axs[0].set(ylabel="kHz")
axs[0].legend(loc="upper right")
axs[1].plot(lg2[m, 0], lg2[m, 1] - lg2[m, 2], lw=0.4)
axs[1].set(ylabel="频率误差 (Hz)")
axs[2].plot(lg2[m, 0], z2["berr"][m] * 1e9, lw=0.3)
axs[2].axhspan(-200, 200, color="g", alpha=0.08)
axs[2].set(ylabel="B′−B (ns)", xlabel="时间 (s)", ylim=(-250, 250))
axs[0].set_title("变频 4 MHz + 5 kHz·sin(0.2t)：在中心频率（df/dt 最大）开启，跟踪一个完整周期")
save(fig, "6_tracking_fm_long.png")

# 6 多次随机开启的统计
cases = res["cases"]
names = list(cases)
fig, axs = plt.subplots(1, 2, figsize=(11, 3.6))
for i, n in enumerate(names):
    lk = [o["t_lock_s"] for o in cases[n] if o["t_lock_s"] is not None]
    be = [o["b_err_max_ns"] for o in cases[n] if o["t_lock_s"] is not None]
    axs[0].plot(lk, [i] * len(lk), "o", ms=4, alpha=0.7)
    axs[1].plot(be, [i] * len(be), "o", ms=4, alpha=0.7)
for a in axs:
    a.set_yticks(range(len(names)), names)
axs[0].axvline(2, c="orange", ls="--")
axs[0].axvline(5, c="r", ls="--")
axs[0].set(xlabel="C 开启到锁定的时间 (s)", xlim=(0, 5.2), title="恢复时间（橙 2 s 发挥要求，红 5 s 基础要求）")
axs[1].axvline(200, c="r", ls="--")
axs[1].set(xlabel="锁定后 max|B′−B| (ns)", xlim=(0, 220), title="码同步误差（红：±200 ns 要求）")
axs[1].set_yticklabels([])
save(fig, "7_trials.png")

# 7 示波器视图：锁定后 20 个码片的 B / B′，A / A′
be = res["demo_fixed"]["b_err_max_ns"] * 1e-9
t = np.arange(0, 20e-6, 1 / 400e6)
fig, axs = plt.subplots(2, 1, figsize=(9, 4), sharex=True)
axs[0].step(t * 1e6, code[np.floor(tx.code_phase(t)).astype(int)] + 1.2, where="post", lw=0.9, label="B")
axs[0].step(t * 1e6, code[np.floor(tx.code_phase(t - be)).astype(int)] - 1.2, where="post", lw=0.9, label="B′")
axs[0].set(yticks=[], title=f"示波器视图（锁定后，取该次运行的最大误差 {be * 1e9:.0f} ns）")
axs[0].legend(loc="right")
dph = np.load(OUT / "demo_fixed.npz")["log"][-1, 3]
axs[1].plot(t * 1e6, np.cos(tx.carrier_phase(t)), lw=0.6, label="A")
axs[1].plot(t * 1e6, np.cos(tx.carrier_phase(t) + dph), lw=0.6, ls="--", label="A′")
axs[1].set(xlabel="时间 (µs)", yticks=[])
axs[1].legend(loc="right")
save(fig, "8_scope.png")
print("ok")
