// Python 파이프라인이 생성하는 timeline.json과 1:1 대응되는 타입.
export interface TimelineWordToken {
  text: string;
  start: number;
  end: number;
}

export interface Subtitle {
  scene: number;
  start: number;
  end: number;
  text: string;
  tokens: TimelineWordToken[];
}

export interface TimelineScene {
  index: number;
  text: string;
  media: string;
  media_type: 'image' | 'video';
  audio: string;
  start: number;
  duration: number;
}

export interface Timeline {
  version: number;
  fps: number;
  width: number;
  height: number;
  total_duration: number;
  watermark?: string;
  scenes: TimelineScene[];
  subtitles: Subtitle[];
}

// Remotion 4는 Composition props가 Record<string, unknown> 제약을 만족해야 한다.
export interface OverlayProps extends Record<string, unknown> {
  timelinePath: string;
  timeline?: Timeline;
}
