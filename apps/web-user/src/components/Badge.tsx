import type { PropsWithChildren } from 'react';

type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

interface BadgeProps extends PropsWithChildren {
  tone?: BadgeTone;
}

export function Badge({ children, tone = 'neutral' }: BadgeProps): JSX.Element {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
