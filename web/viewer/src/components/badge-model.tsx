// A stand-in for the 3D view of UESTC_Badge_20261103.step: a coin seen from above at an angle.

const RING = ["电", "子", "科", "技", "大", "学"]

export function BadgeModel({ zoom = 1 }: { zoom?: number }) {
  return (
    <svg viewBox="0 0 440 320" className="h-full w-full" style={{ transform: `scale(${zoom})`, transition: "transform 160ms ease-out" }}>
      <defs>
        <radialGradient id="face" cx="40%" cy="30%" r="80%">
          <stop offset="0" stopColor="#a9bad6" />
          <stop offset="1" stopColor="#7f94b8" />
        </radialGradient>
        <linearGradient id="edge" x1="0" x2="1">
          <stop offset="0" stopColor="#56688a" />
          <stop offset=".5" stopColor="#7387aa" />
          <stop offset="1" stopColor="#4c5d7c" />
        </linearGradient>
        <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="10" /></filter>
      </defs>
      <ellipse cx="220" cy="214" rx="170" ry="56" fill="#000" opacity=".18" filter="url(#soft)" />
      {/* the edge, then the face */}
      <path d="M50 160 a170 108 0 0 0 340 0 v22 a170 108 0 0 1 -340 0 z" fill="url(#edge)" />
      <ellipse cx="220" cy="160" rx="170" ry="108" fill="url(#face)" stroke="#5d6f91" strokeWidth="1.5" />
      <g transform="translate(220 160) scale(1 .635)" fill="none" stroke="#45577a" strokeLinecap="round">
        <circle r="150" strokeWidth="2.5" opacity=".55" />
        <circle r="104" strokeWidth="3" />
        <circle r="98" strokeWidth="1.2" opacity=".6" />
        {[0, 60, -60].map((a) => (
          <ellipse key={a} rx="86" ry="30" transform={`rotate(${a})`} strokeWidth="3.2" />
        ))}
        <text x="0" y="14" textAnchor="middle" fontSize="46" fontWeight="800" fontFamily="Arial Black, Arial, sans-serif"
              fill="#9fb1cf" stroke="#33435f" strokeWidth="2.4" letterSpacing="1">UeSTC</text>
        {RING.map((c, i) => {
          const a = (-150 + i * 24) * Math.PI / 180
          return (
            <text key={c} x={Math.cos(a) * 127} y={Math.sin(a) * 127 + 9} textAnchor="middle" fontSize="26" fontWeight="700"
                  fill="#5a6c8e" stroke="#33435f" strokeWidth="1" transform={`rotate(${-150 + i * 24 + 90} ${Math.cos(a) * 127} ${Math.sin(a) * 127})`}>{c}</text>
          )
        })}
        <text x="0" y="140" textAnchor="middle" fontSize="34" fontStyle="italic" fontWeight="700" fontFamily="Georgia, serif"
              fill="#8ea2c4" stroke="#33435f" strokeWidth="1.6">1956</text>
      </g>
    </svg>
  )
}
