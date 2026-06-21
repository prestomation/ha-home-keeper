import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

type Feature = {
  title: string;
  description: string;
};

const FEATURES: Feature[] = [
  {
    title: 'Tasks, four ways',
    description:
      'Floating, fixed-calendar, one-off and condition-driven (triggered) tasks — model any kind of upkeep, from filter changes to "renew the passport".',
  },
  {
    title: 'Native Home Assistant surfaces',
    description:
      'Used through a to-do list, an upcoming-tasks calendar, per-device button / next-due / overdue entities, and a bundled dashboard card.',
  },
  {
    title: 'Appliances & inventory',
    description:
      'Give "dumb" appliances a real device page with metadata, parts & wear items, spare-part stock, and a CSV home-inventory export for insurance.',
  },
  {
    title: 'Events & automations',
    description:
      'A bus event for every meaningful change plus visual-editor device triggers like "Task became overdue", and a service for every data action.',
  },
];

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className={styles.heroTitle}>
          {siteConfig.title}
        </Heading>
        <p className={styles.heroTagline}>{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link className="button button--secondary button--lg" to="/docs/intro">
            User Guide
          </Link>
          <Link
            className="button button--outline button--secondary button--lg"
            to="/developer/integrating">
            Developer Guide
          </Link>
        </div>
      </div>
    </header>
  );
}

function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FEATURES.map((feature) => (
            <div key={feature.title} className={clsx('col col--6', styles.feature)}>
              <Heading as="h3">{feature.title}</Heading>
              <p>{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.title}
      description="Track home maintenance and chores in Home Assistant — filters, medicine, and anything else that recurs.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
