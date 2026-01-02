"""
Verification Module - Success verification with 90% threshold.

Components:
- success_verifier.py: Verifies implementation meets requirements with glm-4.7:cloud
"""

from .success_verifier import SuccessVerifier, VerificationResult

__all__ = ['SuccessVerifier', 'VerificationResult']
