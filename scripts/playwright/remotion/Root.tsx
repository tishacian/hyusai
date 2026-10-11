import React from 'react';
import {Composition, getInputProps} from 'remotion';
import {AgentiumDemo, AgentiumDemoProps} from './AgentiumDemo';

const fallbackProps: AgentiumDemoProps = {
  videoSrc: '',
  durationSec: 143.2,
  fps: 25,
  width: 2560,
  height: 1440,
  scenes: [],
};

export const RemotionRoot: React.FC = () => {
  const inputProps = getInputProps<Partial<AgentiumDemoProps>>();
  const props: AgentiumDemoProps = {
    ...fallbackProps,
    ...inputProps,
    scenes: inputProps.scenes || fallbackProps.scenes,
  };
  const fps = props.fps || 25;
  const durationInFrames = Math.ceil((props.durationSec || fallbackProps.durationSec) * fps);

  return (
    <Composition
      id="AgentiumDemo"
      component={AgentiumDemo}
      width={props.width || fallbackProps.width}
      height={props.height || fallbackProps.height}
      fps={fps}
      durationInFrames={durationInFrames}
      defaultProps={props}
    />
  );
};
