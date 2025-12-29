# Role-Based Prompting System
## Specialized LLM System Prompts for Code Generation

**Date:** 2025-11-25
**Feature:** Role-based system prompts for intelligent code generation

---

## Overview

The Intelligent Code Generator now uses **specialized role-based system prompts** to dramatically improve code generation quality. Each file type gets a customized prompt that positions the LLM as a domain expert with specific expertise relevant to the task.

---

## Why This Matters

**Without Role Prompts:**
```
Generate a SQLAlchemy model for User.
```
→ Generic code, may miss best practices, inconsistent quality

**With Role Prompts:**
```
# Your Role: Senior Database Architect & SQLAlchemy Expert

You are a highly experienced database architect specializing in SQLAlchemy ORM design. You have:
- 10+ years of experience designing scalable database schemas
- Deep expertise in SQLAlchemy relationships, constraints, and performance optimization
...

Generate a SQLAlchemy model for User.
```
→ Expert-level code, follows best practices, comprehensive and correct

---

## Specialized Roles

### 1. Database Models (`file_type: "model"`)

**Role:** Senior Database Architect & SQLAlchemy Expert

**Expertise:**
- 10+ years database schema design
- SQLAlchemy relationships and optimization
- Database normalization strategies
- PostgreSQL/MySQL experience

**Generates:**
- Proper foreign key relationships with cascading
- Optimized indexes for performance
- Bidirectional relationships with back_populates
- Comprehensive field docstrings

---

### 2. API Endpoints (`file_type: "api_endpoint"`)

**Role:** Senior Backend Engineer & REST API Specialist

**Expertise:**
- 10+ years building production APIs
- FastAPI and async/await patterns
- REST principles and HTTP standards
- Authentication, rate limiting, validation

**Generates:**
- Proper async/await for I/O
- Comprehensive validation and error handling
- Authentication/authorization checks
- Clear HTTP status codes
- OpenAPI documentation with examples

---

### 3. Pydantic Schemas (`file_type: "schema"`)

**Role:** Data Validation Expert & Pydantic Specialist

**Expertise:**
- Pydantic v2 and FastAPI integration
- Type systems and validation rules
- JSON Schema and OpenAPI specs

**Generates:**
- Precise type hints and validation
- Custom validators for business logic
- Field() constraints
- Optimal serialization configs

---

### 4. CRUD Operations (`file_type: "crud"`)

**Role:** Database Operations Specialist

**Expertise:**
- Transaction management
- Query optimization and N+1 prevention
- Database locking and concurrency
- Caching strategies

**Generates:**
- Proper session management
- Efficient queries with eager/lazy loading
- Constraint violation handling
- Type hints and logging

---

### 5. HTML Templates (`file_type: "template"`)

**Role:** Senior Frontend Engineer & UX/UI Specialist

**Expertise:**
- 10+ years building responsive web interfaces
- HTML5, CSS3, Tailwind CSS, Alpine.js
- UX/UI principles and design patterns
- Real-time features (SSE, WebSocket)
- Web accessibility (WCAG 2.1)

**Generates:**
- Semantic HTML5 for accessibility
- Responsive design with Tailwind
- Interactive Alpine.js components
- Mobile-first approach
- User-friendly error/loading states

---

### 6. JavaScript (`file_type: "javascript"`)

**Role:** Senior JavaScript Engineer & Alpine.js Expert

**Expertise:**
- Alpine.js and reactive programming
- Async/await, Promises, events
- API integration and state management
- Browser APIs and performance
- Real-time features (SSE, WebSocket)

**Generates:**
- Clean Alpine.js components
- Robust error handling
- Loading states and optimistic UI
- Efficient API calls with caching
- Event handling best practices

---

### 7. Security (`file_type: "security"`)

**Role:** Security Engineer & Authentication Specialist

**Expertise:**
- 10+ years secure authentication systems
- JWT, OAuth2, modern auth patterns
- Cryptography and password hashing
- OWASP Top 10 and security practices
- Rate limiting and CORS

**Generates:**
- Secure bcrypt password hashing
- Properly configured JWT
- Token validation and refresh
- Protection against XSS, CSRF, injection
- Security documentation

---

### 8. Configuration (`file_type: "config"`)

**Role:** DevOps Engineer & Configuration Specialist

**Expertise:**
- 12-factor app principles
- Environment variables and secrets management
- Pydantic Settings validation
- Environment-specific configs

**Generates:**
- Clear separation of secrets/public config
- Configuration validation
- Sensible defaults
- Security considerations

---

### 9. Background Workers (`file_type: "worker"`)

**Role:** Distributed Systems Engineer & Celery Expert

**Expertise:**
- Celery, Redis, async task queues
- Task scheduling, retries, failure handling
- Distributed system patterns
- Monitoring and debugging async tasks

**Generates:**
- Proper task configuration (retries, timeouts)
- Comprehensive error handling
- Idempotent operations
- Resource cleanup

---

### 10. Main Application (`file_type: "main"`)

**Role:** Senior Full-Stack Architect & FastAPI Expert

**Expertise:**
- 10+ years architecting web applications
- FastAPI, ASGI servers, middleware
- Application lifecycle events
- CORS, static files, templates, routing
- Production deployments

**Generates:**
- Proper app initialization
- Middleware setup (CORS, logging, errors)
- Static file and template configuration
- Router integration
- Health check endpoints

---

### 11. API Router (`file_type: "api_router"`)

**Role:** API Architect & Routing Specialist

**Expertise:**
- Clean, maintainable API structures
- FastAPI routing and dependencies
- API versioning and OpenAPI docs
- API gateway patterns

**Generates:**
- Logical endpoint grouping
- Proper prefix and tag configuration
- Dependency injection
- Clear OpenAPI structure

---

## Implementation

### Code Location
**File:** `stages/intelligent_generators/llm_code_generator.py`
**Method:** `_get_role_system_prompt(file_type: str) -> str`

### Usage

The role prompt is automatically prepended to every code generation request:

```python
def _build_full_prompt(self, file_spec: FileSpecification, context: str) -> str:
    # Get specialized role-based system prompt
    role_prompt = self._get_role_system_prompt(file_spec.file_type)

    # Build complete prompt
    prompt = f"""{role_prompt}

# Code Generation Task

Generate production-ready code for: **{file_spec.path}**
...
```

---

## Benefits

### 1. Higher Quality Code
LLM generates code as if written by a domain expert, not a generalist.

### 2. Consistency
All files of the same type follow the same best practices and patterns.

### 3. Completeness
Role prompts emphasize production-ready code with error handling, validation, etc.

### 4. Security
Security-focused roles ensure proper authentication, validation, and protection.

### 5. Documentation
Roles emphasize comprehensive docstrings and clear code structure.

---

## Example Output Comparison

### Without Role Prompt

```python
# Generic SQLAlchemy model
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)
    password = Column(String)
```

### With Role Prompt

```python
"""User model for authentication and user management."""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models import Base


class User(Base):
    """
    User account model.

    Represents a user in the system with authentication credentials
    and profile information.

    Attributes:
        id: Primary key, auto-incrementing integer
        email: Unique email address for login (indexed for performance)
        hashed_password: Bcrypt hashed password (never store plain text)
        is_active: Account status flag
        is_verified: Email verification status
        created_at: Account creation timestamp
        updated_at: Last modification timestamp

    Relationships:
        conversations: One-to-many relationship with Conversation model
    """

    __tablename__ = "users"

    # Primary Key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Authentication
    email = Column(String(255), unique=True, nullable=False, index=True,
                   doc="User's email address (unique, indexed)")
    hashed_password = Column(String(255), nullable=False,
                            doc="Bcrypt hashed password")

    # Status flags
    is_active = Column(Boolean, default=True, nullable=False,
                      doc="Whether the account is active")
    is_verified = Column(Boolean, default=False, nullable=False,
                        doc="Whether email has been verified")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False,
                       doc="Account creation timestamp")
    updated_at = Column(DateTime, default=datetime.utcnow,
                       onupdate=datetime.utcnow, nullable=False,
                       doc="Last update timestamp")

    # Relationships
    conversations = relationship("Conversation", back_populates="user",
                               cascade="all, delete-orphan",
                               doc="User's conversation history")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_user_email_active', 'email', 'is_active'),
    )

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', active={self.is_active})>"
```

**Difference:** The role-prompted version includes:
- Comprehensive docstrings
- Proper type constraints (String(255), nullable, unique)
- Performance indexes
- Relationship configuration with cascading
- Repr method for debugging
- Security considerations (hashed_password note)

---

## Extensibility

To add a new role for a custom file type:

```python
role_prompts = {
    # ... existing roles ...

    "custom_type": """# Your Role: [Role Title]

You are a [description of expertise]. You have:
- [Key skill 1]
- [Key skill 2]
- [Key skill 3]

Your task is to generate production-ready [artifact] with:
- [Quality 1]
- [Quality 2]
- [Quality 3]"""
}
```

---

## Testing Impact

**Before Role Prompts:**
- Generated code often needed manual fixes
- Inconsistent patterns across files
- Missing error handling
- Incomplete docstrings

**After Role Prompts:**
- Production-ready code on first generation
- Consistent patterns and best practices
- Comprehensive error handling
- Full documentation

---

## Future Enhancements

1. **Dynamic Role Customization**
   - Allow users to specify their preferred expertise level
   - Adjust role based on project complexity

2. **Role Chaining**
   - Use multiple roles for complex files
   - "Senior Backend Engineer" + "Security Expert" for auth endpoints

3. **Learning from Feedback**
   - Track which roles produce best code
   - Refine role descriptions based on validation results

4. **Context-Aware Roles**
   - Adjust role based on project type
   - E-commerce vs. chat app vs. data analytics

---

## Conclusion

Role-based prompting is a **game-changer** for code generation quality. By positioning the LLM as a domain expert for each file type, we get:

✅ **Expert-level code quality**
✅ **Consistent patterns across the codebase**
✅ **Production-ready implementations**
✅ **Comprehensive documentation**
✅ **Security-conscious design**

This addresses the core issue identified in the root cause analysis: **generic templates** have been replaced with **expert-driven, contextual code generation**.

---

**Feature Status:** ✅ IMPLEMENTED
**Impact:** HIGH - Dramatically improves generated code quality
**User Request:** Implemented exactly as requested
