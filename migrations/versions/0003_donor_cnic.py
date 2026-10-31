"""donor CNIC verification (new table only; no existing table is changed)

Revision ID: 0003_donor_cnic
Revises: 0002_health_camps
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_donor_cnic'
down_revision = '0002_health_camps'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('donor_cnic',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('donor_id', sa.Integer(), nullable=False),
    sa.Column('cnic_number', sa.String(length=15), nullable=False),
    sa.Column('file_data', sa.LargeBinary(), nullable=False),
    sa.Column('file_mime', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('reject_reason', sa.String(length=255), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_by_admin_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['donor_id'], ['donors.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cnic_number')
    )
    with op.batch_alter_table('donor_cnic', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_donor_cnic_donor_id'), ['donor_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_donor_cnic_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('donor_cnic', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_donor_cnic_status'))
        batch_op.drop_index(batch_op.f('ix_donor_cnic_donor_id'))

    op.drop_table('donor_cnic')
