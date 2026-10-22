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
      'Copy a production environment, with its applications, configuration, and data, to a test environment. Test upgrades and changes on that data before you apply them to production.',
  },
  {
    title: 'Back up the whole stack',
    description:
      "Back up every application in an environment with one operation. Each application's driver defines its backup procedure, for example for Neo4j or PostgreSQL.",
  },
  {
    title: 'Upgrade with driver-defined steps',
    description:
      'The driver lists the upgrade steps in order: stop components, run migrations, restart, and verify. You write a multi-step upgrade once, and Styrmin runs the same steps on every upgrade.',
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
          Styrmin deploys, configures, backs up, and upgrades a group of
          applications, such as Infrahub, Ansible, Grafana, and Prometheus, as
          one stack on Kubernetes.
        </p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/introduction/why-styrmin">
            Why Styrmin?
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/installation/quickstart">
            Quickstart
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/installation">
            Install Styrmin
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/">
            Browse documentation
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
              Operations on a whole environment
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
