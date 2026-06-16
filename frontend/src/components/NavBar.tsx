import { NavLink } from 'react-router-dom'

interface Props {
  navScrolled: boolean
}

export default function NavBar({ navScrolled }: Props) {
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
          <NavLink to="/dashboard" className={({ isActive }) => `nf-nav-link ${isActive ? 'active' : ''}`}>
            Dashboard
          </NavLink>
          <NavLink to="/about" className={({ isActive }) => `nf-nav-link ${isActive ? 'active' : ''}`}>
            About
          </NavLink>
        </div>
      </div>
    </nav>
  )
}
