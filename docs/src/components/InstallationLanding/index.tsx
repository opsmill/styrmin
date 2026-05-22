import type {ComponentType, ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useEmblaCarousel from 'embla-carousel-react';
import Autoplay from 'embla-carousel-autoplay';

import {
  DigitalOceanLogo,
  EksLogo,
  GkeLogo,
  K3sLogo,
  KubeadmLogo,
  VclusterLogo,
} from './logos';
import styles from './styles.module.css';

type Platform = {
  id: string;
  name: string;
  subtitle: string;
  description: string;
  Logo: ComponentType<{className?: string}>;
  href?: string;
  badge?: string;
};

const platforms: Platform[] = [
  {
    id: 'vcluster',
    name: 'Local laptop (vcluster)',
    subtitle: 'Try Styrmin in minutes',
    description:
      'Run the full Styrmin stack on Docker via vCluster — same path as `uv run invoke start`, broken into explicit steps.',
    Logo: VclusterLogo,
    href: '/docs/installation/vcluster-local',
  },
  {
    id: 'digitalocean',
    name: 'DigitalOcean',
    subtitle: 'Managed Kubernetes',
    description:
      'DOKS with two Load Balancers, Spaces-backed Velero backups, and hostname-based ingress — production-ready in one guide.',
    Logo: DigitalOceanLogo,
    href: '/docs/installation/digitalocean',
  },
  {
    id: 'gke',
    name: 'Google GKE',
    subtitle: 'Google Cloud',
    description:
      'Run Styrmin on Google Kubernetes Engine. Guide is being written — content lands soon.',
    Logo: GkeLogo,
    href: '/docs/installation/gke',
    badge: 'Coming soon',
  },
  {
    id: 'eks',
    name: 'Amazon EKS',
    subtitle: 'AWS',
    description:
      'Elastic Kubernetes Service on AWS. Walkthrough planned — track progress in the roadmap.',
    Logo: EksLogo,
    badge: 'Planned',
  },
  {
    id: 'k3s',
    name: 'k3s',
    subtitle: 'Lightweight Kubernetes',
    description:
      'Single- or multi-node k3s clusters on bare metal or VMs. Guide planned for the self-hosted track.',
    Logo: K3sLogo,
    badge: 'Planned',
  },
  {
    id: 'kubeadm',
    name: 'kubeadm',
    subtitle: 'Self-hosted Kubernetes',
    description:
      'Bring-your-own kubeadm cluster. Use the prerequisites guide today; full walkthrough coming.',
    Logo: KubeadmLogo,
    badge: 'Planned',
  },
];

function LogoStrip(): ReactNode {
  const [emblaRef] = useEmblaCarousel(
    {loop: true, align: 'start', dragFree: true},
    [Autoplay({delay: 2200, stopOnInteraction: false, stopOnMouseEnter: true})],
  );

  // Duplicate the list so the loop has enough slides to scroll smoothly.
  const slides = [...platforms, ...platforms];

  return (
    <div className={styles.logoStrip}>
      <div className={styles.logoFade + ' ' + styles.logoFadeLeft} aria-hidden />
      <div className={styles.logoViewport} ref={emblaRef}>
        <div className={styles.logoContainer}>
          {slides.map((p, i) => {
            const content = (
              <>
                <p.Logo className={styles.logoIcon} />
                <span className={styles.logoLabel}>{p.name}</span>
              </>
            );
            return p.href ? (
              <Link
                key={`${p.id}-${i}`}
                to={p.href}
                className={styles.logoSlide}>
                {content}
              </Link>
            ) : (
              <span key={`${p.id}-${i}`} className={styles.logoSlide}>
                {content}
              </span>
            );
          })}
        </div>
      </div>
      <div className={styles.logoFade + ' ' + styles.logoFadeRight} aria-hidden />
    </div>
  );
}

function PlatformCard({platform}: {platform: Platform}): ReactNode {
  const body = (
    <>
      <div className={styles.cardHeader}>
        <platform.Logo className={styles.cardLogo} />
        <div>
          <div className={styles.cardSubtitle}>{platform.subtitle}</div>
          <h3 className={styles.cardTitle}>{platform.name}</h3>
        </div>
      </div>
      <p className={styles.cardDescription}>{platform.description}</p>
      {platform.badge ? (
        <span className={styles.cardBadge}>{platform.badge}</span>
      ) : (
        <span className={styles.cardCta}>Get started →</span>
      )}
    </>
  );

  if (platform.href) {
    return (
      <Link to={platform.href} className={styles.card}>
        {body}
      </Link>
    );
  }

  return <div className={`${styles.card} ${styles.cardDisabled}`}>{body}</div>;
}

export default function InstallationLanding(): ReactNode {
  return (
    <div className={styles.landing}>
      <div className="container">
        <header className={styles.hero}>
          <h1 className={styles.heroTitle}>Deploy Styrmin anywhere</h1>
          <p className={styles.heroLede}>
            Styrmin runs on any conformant Kubernetes cluster. Pick the platform
            you want to deploy on — each guide walks through prerequisites,
            ingress, backups, and the first Styrmin install end to end.
          </p>
        </header>

        <LogoStrip />

        <h2 className={styles.cardsHeading}>Pick your platform</h2>
        <div className={styles.cardGrid}>
          {platforms.map((p) => (
            <PlatformCard key={p.id} platform={p} />
          ))}
        </div>
      </div>
    </div>
  );
}
