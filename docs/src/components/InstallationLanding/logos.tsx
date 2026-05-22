import type {ReactNode} from 'react';

type LogoProps = {className?: string};

export function DigitalOceanLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="DigitalOcean logo"
      role="img">
      <path
        fill="#0080FF"
        d="M16 32v-6.2c6.6 0 11.7-6.5 9.2-13.4-.9-2.5-3-4.6-5.5-5.5-7-2.5-13.4 2.7-13.4 9.2H0C0 5.8 10.2-2.3 21.3 1.2c4.8 1.5 8.7 5.3 10.2 10.2C35 22.4 26.6 32 16 32z"
      />
      <path fill="#0080FF" d="M16 25.8H9.9v-6.2H16v6.2z" />
      <path fill="#0080FF" d="M9.9 30.4H5.2v-4.7h4.7v4.7z" />
      <path fill="#0080FF" d="M5.2 25.8H1.3v-3.9h3.9v3.9z" />
    </svg>
  );
}

export function GkeLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Google Cloud / GKE logo"
      role="img">
      <path fill="#EA4335" d="M20.5 9.5h2.9l.6-.6.2-2.5C18.9 2 11.6 2.5 7.4 7.6c-1.2 1.4-2 3-2.5 4.7 1-.6 3.4-.2 3.4-.2l5-.8s.3-.4.4-.4c2.2-2.5 6-2.7 6.8-1.4z" />
      <path fill="#4285F4" d="M27 12.3c-.6-2.1-1.7-4-3.4-5.5l-4 4c1.5 1.2 2.4 3.1 2.4 5v.6c1.7 0 3.1 1.4 3.1 3.1s-1.4 3.1-3.1 3.1H16l-.6.6v3.7l.6.6h6c4.3 0 7.7-3.3 7.7-7.6.1-2.6-1.2-5.1-2.7-6.6z" />
      <path fill="#34A853" d="M10 26h6v-5h-6c-.4 0-.9-.1-1.3-.3l-.9.3-2.6 2.5-.2.7c1.4 1.1 3.2 1.8 5 1.8z" />
      <path fill="#FBBC05" d="M10 10.6c-4.3 0-7.7 3.5-7.6 7.7 0 2.4 1.1 4.6 3 6l4.4-4.4c-1.6-.7-2.3-2.5-1.6-4 .7-1.6 2.5-2.3 4-1.6.7.3 1.3.9 1.6 1.6l4.4-4.4c-1.8-2.4-4.7-3.9-7.7-3.9-.2 0-.4 0-.5 0z" />
    </svg>
  );
}

export function K3sLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="k3s logo"
      role="img">
      <path
        fill="#FFC61C"
        d="M16 2 4 8v9.4c0 7.4 5.1 14.3 12 16 6.9-1.7 12-8.6 12-16V8L16 2z"
      />
      <path
        fill="#1F1F1F"
        d="M11 11h2v4l3.5-4h2.3l-3.8 4.4 4 6.6h-2.5l-3-5-.5.6V22h-2V11z"
      />
    </svg>
  );
}

export function VclusterLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="vcluster logo"
      role="img">
      <circle cx="16" cy="16" r="14" fill="#00B4D8" />
      <path
        fill="#FFFFFF"
        d="M9 10h3l4 9 4-9h3l-6 13h-2L9 10z"
      />
    </svg>
  );
}

export function KubeadmLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="kubeadm / Kubernetes logo"
      role="img">
      <path
        fill="#326CE5"
        d="M16 2 3.5 8v8L16 22l12.5-6V8L16 2z"
      />
      <path
        fill="#FFFFFF"
        d="m16 8-7 4v4l7 4 7-4v-4l-7-4zm0 2.5L20 13l-4 2.3L12 13l4-2.5z"
      />
    </svg>
  );
}

export function EksLogo({className}: LogoProps): ReactNode {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Amazon EKS logo"
      role="img">
      <path fill="#FF9900" d="M16 2 3 9v14l13 7 13-7V9L16 2z" />
      <path
        fill="#FFFFFF"
        d="M16 8 9 12v8l7 4 7-4v-8l-7-4zm0 2 5 3v6l-5 3-5-3v-6l5-3z"
      />
    </svg>
  );
}
