import React from 'react';
import {
  CalculateMetadataFunction,
  Composition,
  staticFile,
} from 'remotion';
import {ShortsOverlay} from './ShortsOverlay';
import {OverlayProps, Timeline} from './types';

// Python 파이프라인이 public/timeline.json 으로 복사해 둔 타임라인을 읽어
// fps/해상도/총 프레임을 자동 결정 → FFmpeg 베이스 영상과 프레임 단위 일치.
// (번들은 브라우저 컨텍스트에서 평가되므로 fs 대신 staticFile + fetch 사용)
export const calcOverlay: CalculateMetadataFunction<OverlayProps> = async ({
  props,
  abortSignal,
}) => {
  const res = await fetch(staticFile(props.timelinePath), {
    signal: abortSignal,
  });
  const timeline = (await res.json()) as Timeline;
  return {
    durationInFrames: Math.max(
      1,
      Math.round(timeline.total_duration * timeline.fps),
    ),
    fps: timeline.fps,
    width: timeline.width,
    height: timeline.height,
    props: {...props, timeline},
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ShortsOverlay"
      component={ShortsOverlay}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={150}
      defaultProps={{timelinePath: 'timeline.json', timeline: undefined}}
      calculateMetadata={calcOverlay}
    />
  );
};
