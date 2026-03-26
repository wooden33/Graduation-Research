ADDITIONAL_INCLUDES_TEXT = """
## Additional Includes
The following files are included as context for the above source code. These files typically contain libraries or other necessary dependencies to help write more comprehensive tests:
======
{included_files}
======
"""

ADDITIONAL_INSTRUCTIONS_TEXT = """
## Additional Instructions
Please consider the following instructions while generating the unit tests:
======
{additional_instructions}
======
"""

FAILED_TESTS_TEXT = """
## Failed Tests
Please avoid regenerating these tests and consider their failure reasons when creating new tests to ensure improved outcomes.
if the test failed due to AssertionError, you can try to fix the failed assertion when generating new tests. 

{failed_test_runs}
"""

TEST_CLASS_JUNIT_3 = """
import junit.framework.TestCase;

public class {test_class_name} extends TestCase {{
    public void testPlaceHolder() {{
        assertTrue(true); 
    }}
}}
"""

TEST_CLASS_JUNIT_4 = """
import org.junit.Before;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;

public class {test_class_name} {{

    @Test
    public void  testPlaceHolder() {{
        assertTrue(true); 
    }}
}}

"""

TEST_CLASS_JUNIT_5 = """
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class {test_class_name} {{

    @Test
    void testPlaceHolder() {{
        assertTrue(true);
    }}
}}
"""

TEST_CLASS_JUNIT_4_IMPORTS = """
import org.junit.Before;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
"""

TEST_CLASS_JUNIT_3_IMPORTS = """
import junit.framework.TestCase;
"""

TEST_CLASS_JUNIT_5_IMPORTS = """
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
"""