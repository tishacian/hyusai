import React from 'react';
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

export interface AgentiumScene {
  id: string;
  start: number;
  end: number;
  stage?: string;
  title?: string;
  kicker?: string;
}

export interface AgentiumDemoProps {
  videoSrc: string;
  durationSec: number;
  fps: number;
  width: number;
  height: number;
  scenes: AgentiumScene[];
}

const cyan = '#22d3ee';
const softCyan = '#67e8f9';
const white = '#f8fafc';
const muted = 'rgba(203, 213, 225, 0.72)';
const panel = 'rgba(2, 6, 23, 0.58)';
const stroke = 'rgba(34, 211, 238, 0.26)';

function clamp(value: number, min = 0, max = 1): number {
  return Math.max(min, Math.min(max, value));
}

function fadeWindow(frame: number, start: number, end: number, fade = 14): number {
  return Math.min(
    interpolate(frame, [start, start + fade], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
    interpolate(frame, [end - fade, end], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
  );
}

function activeScene(scenes: AgentiumScene[], second: number): AgentiumScene | null {
  if (scenes.length === 0) return null;
  return scenes.find((scene) => second >= scene.start && second < scene.end) || scenes[scenes.length - 1];
}

const LogoLockup: React.FC = () => (
  <div style={{
    position: 'absolute',
    left: 32,
    top: 32,
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    opacity: 0.9,
  }}>
    <Img src={staticFile('agentium-mark.svg')} style={{width: 42, height: 42, borderRadius: 10}} />
    <div style={{fontFamily: 'Inter, Arial, sans-serif'}}>
      <div style={{fontSize: 20, fontWeight: 700, color: white, letterSpacing: 0}}>Agentium</div>
      <div style={{fontSize: 10, fontWeight: 700, color: muted, textTransform: 'uppercase', letterSpacing: 2.1}}>
        Sovereign AI systems
      </div>
    </div>
  </div>
);

const ProgressRail: React.FC<{scenes: AgentiumScene[]; second: number; duration: number}> = ({scenes, second, duration}) => {
  const progress = clamp(second / duration);
  return (
    <div style={{position: 'absolute', left: 56, right: 56, bottom: 34, height: 20}}>
      <div style={{position: 'absolute', left: 0, right: 0, top: 9, height: 2, background: 'rgba(148, 163, 184, 0.16)'}} />
      <div style={{position: 'absolute', left: 0, top: 8, width: `${progress * 100}%`, height: 3, background: `linear-gradient(90deg, ${cyan}, #8b5cf6)`, boxShadow: `0 0 18px ${cyan}`}} />
      {scenes.map((scene) => {
        const left = clamp(scene.start / duration) * 100;
        const isActive = second >= scene.start && second < scene.end;
        return (
          <div key={scene.id} style={{
            position: 'absolute',
            left: `${left}%`,
            top: isActive ? 4 : 7,
            width: isActive ? 4 : 2,
            height: isActive ? 12 : 7,
            background: isActive ? softCyan : 'rgba(203, 213, 225, 0.42)',
            boxShadow: isActive ? `0 0 16px ${cyan}` : 'none',
          }} />
        );
      })}
    </div>
  );
};

const ChapterFlash: React.FC<{scene: AgentiumScene | null; localFrame: number}> = ({scene, localFrame}) => {
  if (!scene) return null;
  const opacity = fadeWindow(localFrame, 0, 96, 14);
  const translate = interpolate(localFrame, [0, 24], [16, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{
      position: 'absolute',
      left: 54,
      bottom: 76,
      width: 650,
      padding: '16px 20px 18px 20px',
      borderLeft: `3px solid ${cyan}`,
      borderTop: `1px solid ${stroke}`,
      borderBottom: `1px solid rgba(148, 163, 184, 0.12)`,
      background: 'linear-gradient(90deg, rgba(2, 6, 23, 0.72), rgba(2, 6, 23, 0.18))',
      backdropFilter: 'blur(12px)',
      opacity,
      transform: `translateY(${translate}px)`,
      fontFamily: 'Inter, Arial, sans-serif',
    }}>
      <div style={{display: 'flex', gap: 12, alignItems: 'center', marginBottom: 7}}>
        <span style={{
          color: '#020617',
          background: cyan,
          borderRadius: 999,
          padding: '4px 10px',
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 1.1,
        }}>
          {(scene.stage || 'SYSTEM').toUpperCase()}
        </span>
        <span style={{color: softCyan, fontSize: 12, fontWeight: 800, letterSpacing: 1.9, textTransform: 'uppercase'}}>
          {scene.kicker || 'Agentium'}
        </span>
      </div>
      <div style={{color: white, fontSize: 30, lineHeight: 1.12, fontWeight: 720, letterSpacing: 0}}>
        {scene.title || scene.id}
      </div>
    </div>
  );
};

const TransitionWash: React.FC<{scenes: AgentiumScene[]; second: number; fps: number}> = ({scenes, second, fps}) => {
  const frame = second * fps;
  const starts = scenes.slice(1).map((scene) => Math.round(scene.start * fps));
  const nearest = starts.find((start) => frame >= start && frame <= start + 24);
  if (nearest === undefined) return null;
  const local = frame - nearest;
  const opacity = interpolate(local, [0, 7, 24], [0, 0.35, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const sweep = interpolate(local, [0, 24], [-12, 112], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{pointerEvents: 'none', opacity}}>
      <div style={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        left: `${sweep}%`,
        width: 3,
        background: cyan,
        boxShadow: `0 0 48px 18px rgba(34, 211, 238, 0.32)`,
      }} />
      <div style={{
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(90deg, transparent, rgba(34, 211, 238, 0.12), transparent)',
        transform: `translateX(${sweep - 50}%)`,
      }} />
    </AbsoluteFill>
  );
};

const Intro: React.FC<{frame: number}> = ({frame}) => {
  const opacity = interpolate(frame, [0, 20, 62, 92], [1, 1, 0.72, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const titleOpacity = interpolate(frame, [8, 28], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{opacity, background: 'radial-gradient(circle at 18% 15%, rgba(34, 211, 238, 0.22), transparent 30%), linear-gradient(135deg, rgba(2,6,23,0.78), rgba(2,6,23,0.18))'}}>
      <div style={{
        position: 'absolute',
        left: 64,
        top: 96,
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        fontFamily: 'Inter, Arial, sans-serif',
        opacity: titleOpacity,
      }}>
        <Img src={staticFile('agentium-mark.svg')} style={{width: 68, height: 68, borderRadius: 16}} />
        <div>
          <div style={{fontSize: 36, fontWeight: 760, color: white, letterSpacing: 0}}>Agentium</div>
          <div style={{fontSize: 13, color: softCyan, fontWeight: 800, letterSpacing: 2.4, textTransform: 'uppercase'}}>
            Operating system for governed intelligent systems
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Outro: React.FC<{frame: number; totalFrames: number}> = ({frame, totalFrames}) => {
  const opacity = interpolate(frame, [totalFrames - 85, totalFrames - 34, totalFrames], [0, 1, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div style={{
      position: 'absolute',
      right: 58,
      bottom: 78,
      padding: '14px 18px',
      border: `1px solid ${stroke}`,
      background: panel,
      backdropFilter: 'blur(14px)',
      color: white,
      opacity,
      fontFamily: 'Inter, Arial, sans-serif',
    }}>
      <div style={{fontSize: 12, color: softCyan, fontWeight: 800, letterSpacing: 2, textTransform: 'uppercase'}}>
        Agentium
      </div>
      <div style={{fontSize: 22, fontWeight: 720, marginTop: 4, letterSpacing: 0}}>
        Trusted, auditable, sovereign systems.
      </div>
    </div>
  );
};

export const AgentiumDemo: React.FC<AgentiumDemoProps> = ({videoSrc, scenes, durationSec, fps}) => {
  const frame = useCurrentFrame();
  const config = useVideoConfig();
  const second = frame / config.fps;
  const scene = activeScene(scenes, second);
  const localFrame = scene ? frame - Math.round(scene.start * config.fps) : frame;
  const totalFrames = Math.ceil(durationSec * fps);
  const resolvedVideoSrc = videoSrc.startsWith('static:') ? staticFile(videoSrc.slice('static:'.length)) : videoSrc;

  return (
    <AbsoluteFill style={{background: '#020617'}}>
      {videoSrc ? (
        <OffthreadVideo
          src={resolvedVideoSrc}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      ) : null}
      <AbsoluteFill style={{
        background: 'linear-gradient(180deg, rgba(2,6,23,0.18), transparent 16%, transparent 82%, rgba(2,6,23,0.34))',
        pointerEvents: 'none',
      }} />
      <TransitionWash scenes={scenes} second={second} fps={config.fps} />
      <LogoLockup />
      <div style={{
        position: 'absolute',
        right: 46,
        top: 38,
        color: softCyan,
        fontFamily: 'Inter, Arial, sans-serif',
        fontSize: 13,
        fontWeight: 800,
        letterSpacing: 2.2,
        textTransform: 'uppercase',
        opacity: 0.82,
        textShadow: '0 0 18px rgba(34, 211, 238, 0.35)',
      }}>
        AI Operating System 2026
      </div>
      <ChapterFlash scene={scene} localFrame={localFrame} />
      <ProgressRail scenes={scenes} second={second} duration={durationSec} />
      <Intro frame={frame} />
      <Outro frame={frame} totalFrames={totalFrames} />
    </AbsoluteFill>
  );
};
