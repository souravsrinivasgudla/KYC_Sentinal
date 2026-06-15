import { Component, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <>
          <section className="nf-hero nf-hero-compact nf-profile-detail-hero">
            <div className="nf-hero-content">
              <Link to="/profiles" className="nf-profile-back">
                <ArrowLeft size={16} />
                Back to Profiles
              </Link>
              <h1>Profile Error</h1>
            </div>
          </section>
          <main className="nf-main nf-profile-detail nf-profile-detail-body">
            <div className="nf-card nf-empty">
              <p>Something went wrong loading this profile. Please go back and try again.</p>
            </div>
          </main>
        </>
      )
    }
    return this.props.children
  }
}
