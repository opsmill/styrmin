import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

const features = [
  {
    title: 'Declarative Deployments',
    description:
      'Define your deployment specifications declaratively through Application Drivers. Styrmin reconciles desired state with current state automatically.',
  },
  {
    title: 'Driver-Based Architecture',
    description:
      'Application Drivers encapsulate Helm charts, configuration templates, and lifecycle actions into versioned, reusable deployment packages.',
  },
  {
    title: 'Multi-Cluster Support',
    description:
      'Manage deployments across multiple Kubernetes clusters and environments from a single platform.',
  },
];

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={`hero hero--primary ${styles.heroBanner}`}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/getting-started/overview">
            Get Started
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/category/installation">
            Install Styrmin
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Home"
      description="Styrmin - Deployment Orchestration for Kubernetes">
      <HomepageHeader />
      <main>
        <section style={{padding: '2rem 0'}}>
          <div className="container">
            <div className="row">
              {features.map((feature) => (
                <div key={feature.title} className="col col--4">
                  <div className="text--center padding-horiz--md" style={{padding: '1rem'}}>
                    <Heading as="h3">{feature.title}</Heading>
                    <p>{feature.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
