import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {OverlayProps, Timeline} from './types';

const FONT =
  'Pretendard Variable, Pretendard, "Noto Sans KR", "Malgun Gothic", -apple-system, sans-serif';

// ── 상단 진행바 ────────────────────────────────────────
const ProgressBar: React.FC<{color?: string}> = ({color = '#FF3B5C'}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  const w = interpolate(frame, [0, durationInFrames - 1], [0, width], {
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        height: 10,
        width: '100%',
        backgroundColor: 'rgba(255,255,255,0.15)',
      }}
    >
      <div style={{height: '100%', width: w, backgroundColor: color}} />
    </div>
  );
};

// ── 상단 워터마크 ──────────────────────────────────────
const Watermark: React.FC<{text: string}> = ({text}) => (
  <div
    style={{
      position: 'absolute',
      top: 48,
      right: 48,
      fontFamily: FONT,
      fontSize: 36,
      fontWeight: 700,
      color: 'rgba(255,255,255,0.85)',
      textShadow: '0 2px 8px rgba(0,0,0,0.8)',
      letterSpacing: 0.5,
    }}
  >
    {text}
  </div>
);

// ── 자막 한 줄 (karaoke 토큰 하이라이트 + 팝인) ────────
const SubtitleLine: React.FC<{
  text: string;
  start: number;
  end: number;
  tokens: {text: string; start: number; end: number}[];
}> = ({text, start, tokens}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;

  // 문장 전환 시 팝인(spring) — 쇼츠 특유의 리듬감
  const startFrame = Math.round(start * fps);
  const pop = spring({
    frame: frame - startFrame,
    fps,
    config: {damping: 14, mass: 0.6, stiffness: 180},
  });
  const scale = 0.82 + 0.18 * pop;

  const base: React.CSSProperties = {
    display: 'inline-block',
    marginRight: '0.32em',
    fontWeight: 800,
    WebkitTextStroke: '3px rgba(0,0,0,0.9)',
    paintOrder: 'stroke fill',
    textShadow: '0 6px 22px rgba(0,0,0,0.75)',
  };

  return (
    <div
      style={{
        transform: `scale(${scale})`,
        opacity: pop,
        textAlign: 'center',
        fontSize: 72,
        lineHeight: 1.35,
        color: '#FFFFFF',
        fontFamily: FONT,
        wordBreak: 'keep-all',
      }}
    >
      {tokens && tokens.length > 0
        ? tokens.map((tok, i) => (
            <span
              key={i}
              style={{
                ...base,
                color: t >= tok.start ? '#FFE14D' : '#FFFFFF',
              }}
            >
              {tok.text}
            </span>
          ))
        : text}
    </div>
  );
};

// ── 메인 오버레이 (투명 배경) ──────────────────────────
export const ShortsOverlay: React.FC<OverlayProps> = ({timeline}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (!timeline) return <AbsoluteFill style={{backgroundColor: 'transparent'}} />;

  const t = frame / fps;
  const active = timeline.subtitles.find((s) => t >= s.start && t < s.end);

  return (
    <AbsoluteFill style={{backgroundColor: 'transparent'}}>
      {/* 하단 가독성 그라데이션 */}
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: 560,
          background:
            'linear-gradient(to top, rgba(0,0,0,0.55), rgba(0,0,0,0))',
        }}
      />

      <ProgressBar />
      {timeline.watermark ? <Watermark text={timeline.watermark} /> : null}

      {active ? (
        <div
          style={{
            position: 'absolute',
            bottom: 300, // 쇼츠 UI(좋아요/댓글) 안전 영역 위
            left: 60,
            right: 60,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <SubtitleLine
            key={`${active.scene}-${active.start}`}
            text={active.text}
            start={active.start}
            end={active.end}
            tokens={active.tokens}
          />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
