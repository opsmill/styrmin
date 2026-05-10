import type {ReactNode} from 'react';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import Link from '@docusaurus/Link';

export default function NotFound(): ReactNode {
  return (
    <Layout title="Page Not Found">
      <main
        className="container margin-vert--xl"
        style={{textAlign: 'center'}}>
        <div className="row">
          <div className="col col--6 col--offset-3">
            <Heading as="h1">Page Not Found</Heading>
            <p>
              The page you're looking for doesn't exist or has been moved.
            </p>
            <div style={{marginTop: '2rem'}}>
              <Link
                className="button button--primary button--lg"
                to="/"
                style={{marginRight: '1rem'}}>
                Go to Homepage
              </Link>
              <Link
                className="button button--secondary button--lg"
                to="/docs/getting-started/overview">
                Browse Documentation
              </Link>
            </div>
          </div>
        </div>
      </main>
    </Layout>
  );
}
