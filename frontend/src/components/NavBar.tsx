import { NavLink } from 'react-router-dom'
import { Sparkles } from 'lucide-react'

interface Props {
  groqOk: boolean
  navScrolled: boolean
}

export default function NavBar({ groqOk, navScrolled }: Props) {
  return (
    <nav className={`nf-nav ${navScrolled ? 'scrolled' : ''}`}>
      <div className="nf-nav-left">
        <NavLink to="/" className="nf-logo">KYC SENTINEL</NavLink>
        <div className="nf-nav-links">
          <NavLink to="/" className={({ isActive }) => `nf-nav-link ${isActive ? 'active' : ''}`} end>
            Home
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => `nf-nav-link ${isActive ? 'active' : ''}`}>
            Profiles
          </NavLink>
        </div>
      </div>
      <div className="nf-nav-tags">
        {groqOk && (
          <span className="nf-tag">
            <Sparkles size={10} style={{ marginRight: 4 }} />
            Groq AI
          </span>
        )}
        <span className="nf-tag">AMD Ready</span>
      </div>
    </nav>
  )
}
