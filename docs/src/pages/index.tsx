import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

const features = [
  {
    title: 'Clone an entire environment',
    description:
      'Duplicate production — applications, configuration, and live data — into a test environment. Validate upgrades and changes against real data before touching production.',
  },
  {
    title: 'Back up the whole stack',
    description:
      'Trigger backups across every application in an environment in a single operation. Each driver knows how to back up its application correctly, so Neo4j and Postgres are both handled the right way.',
  },
  {
    title: 'Upgrade reliably',
    description:
      'Upgrade applications through driver-defined sequences — stop components, run migrations, restart, verify. Complex upgrade processes are encoded once and run the same way every time.',
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
        <p className={styles.heroLede}>
          Styrmin manages the full lifecycle of your infrastructure automation
          stack — Infrahub, Ansible, Grafana, Prometheus — as a single system,
          not application by application.
        </p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/getting-started/why-styrmin">
            Why Styrmin?
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/getting-started/quickstart">
            Quickstart
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/installation">
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
      description="Styrmin — lifecycle management for your infrastructure automation stack.">
      <HomepageHeader />
      <main>
        <section className={styles.featuresSection}>
          <div className="container">
            <Heading as="h2" className={styles.sectionHeading}>
              What nothing else gives you
            </Heading>
            <div className="row">
              {features.map((feature) => (
                <div key={feature.title} className="col col--4">
                  <div className={styles.featureCard}>
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
